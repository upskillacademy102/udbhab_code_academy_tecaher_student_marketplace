"""
Views for the student_requirement app.

Endpoints (wired up in apps/student_requirement/urls.py, next file):
    GET/POST             /api/v1/student-requirements/          -> StudentRequirementListCreateView
    GET/PUT/PATCH/DELETE  /api/v1/student-requirements/{id}/      -> StudentRequirementDetailView

Design note: per the spec's permissions ("Student: ... View Own
Requirements"), this app exposes ONLY the requesting student's own
requirements - there is no "list all requirements" or "view another
student's requirement" endpoint here. Teachers discover matching
requirements exclusively through apps.lead_engine's Lead records
(with contact details hidden), never by browsing this app directly.
"""

import logging

from django.db import transaction
from django.db.models import Exists, OuterRef
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.lead_engine.models import Lead
from apps.lead_engine.tasks import process_requirement_leads
from apps.student_requirement.models import (
    LeadDistributionStatus,
    StudentRequirement,
    StudentScheduleException,
    StudentSchedulePreference,
)
from apps.student_requirement.serializers import (
    StudentRequirementSerializer,
    StudentRequirementWriteSerializer,
    StudentScheduleExceptionSerializer,
    StudentSchedulePreferenceSerializer,
)
from apps.trust.gates import (
    NotRiskSuspended,
    RequireVerifiedToPostRequirement,
    default_permissions_with,
)

logger = logging.getLogger("apps.student_requirement")


def _with_unlock_annotation(queryset):
    """
    Annotates `has_unlocked_lead` (True once any Lead for the row has
    contact_unlocked=True) via a single EXISTS subquery per row, rather
    than StudentRequirementSerializer.get_has_unlocked_lead() falling back
    to one `.leads.filter(...).exists()` query per requirement in a list
    response - the same N+1-avoidance shape as prefetch_related, just for
    a boolean instead of a related object list.
    """
    return queryset.annotate(
        has_unlocked_lead=Exists(
            Lead.objects.filter(
                student_requirement=OuterRef("pk"), contact_unlocked=True
            )
        )
    )


@extend_schema_view(
    get=extend_schema(
        tags=["Student Requirements"], responses=StudentRequirementSerializer(many=True)
    ),
    post=extend_schema(
        tags=["Student Requirements"],
        request=StudentRequirementWriteSerializer,
        responses={202: StudentRequirementSerializer},
        summary="Create a requirement; lead matching + distribution run asynchronously (202)",
    ),
)
class StudentRequirementListCreateView(generics.ListCreateAPIView):
    """
    GET: List the authenticated student's own requirements.
    POST: Submit a new requirement. Lead generation and tiered
    distribution are handed to a Celery worker, so this returns
    202 Accepted as soon as the requirement is committed.
    """

    # Both gates are no-ops unless their flag is on, and only gate writes.
    permission_classes = default_permissions_with(
        RequireVerifiedToPostRequirement, NotRiskSuspended
    )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StudentRequirement.objects.none()
        return _with_unlock_annotation(
            StudentRequirement.objects.filter(student=self.request.user)
            .select_related("subject", "city")
            .prefetch_related("schedule_preferences", "preferred_languages__language")
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StudentRequirementWriteSerializer
        return StudentRequirementSerializer

    def get_serializer_context(self):
        # Required so StudentRequirementWriteSerializer.validate()
        # can access self.context["request"].user for the duplicate
        # requirement check.
        context = super().get_serializer_context()
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = StudentRequirementSerializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def create(self, request, *args, **kwargs):
        """
        Validate + persist the requirement, then hand lead generation and
        tiered distribution to a Celery worker. The response returns as
        soon as the requirement is committed - it does NOT wait for
        candidate discovery, time-overlap math, location matching or tier
        evaluation, all of which can be slow with many verified teachers.

        The Celery task is enqueued via ``transaction.on_commit`` so a
        worker can never pick up a requirement that has not committed
        (or that a later error rolled back).
        """
        from apps.trust.services.requirement_velocity_service import (
            RequirementVelocityService,
        )

        RequirementVelocityService.guard(request.user)

        serializer = StudentRequirementWriteSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        held = RequirementVelocityService.should_hold(request.user)
        target_status = (
            LeadDistributionStatus.HELD if held else LeadDistributionStatus.QUEUED
        )

        with transaction.atomic():
            requirement = serializer.save(student=request.user)
            StudentRequirement.objects.filter(pk=requirement.pk).update(
                lead_distribution_status=target_status
            )
            requirement.lead_distribution_status = target_status

            requirement_pk = str(requirement.pk)

            def _enqueue_distribution():
                if held:
                    # Shadow-limited student: created but not distributed. A
                    # failure opening the review item must not 500 the POST -
                    # the requirement is already saved (and HELD, so the retry
                    # sweep will not distribute it); the daily risk sweep will
                    # re-surface the student for review.
                    try:
                        from apps.trust.models import ManualReviewKind
                        from apps.trust.services.trust_service import TrustService

                        TrustService.open_review_item(
                            kind=ManualReviewKind.LEAD_QUALITY,
                            summary=f"Held requirement from shadow-limited student {request.user.email}",
                            subject_user=request.user,
                            payload={"requirement_id": requirement_pk},
                            dedupe_key=f"held:{request.user.id}",
                            priority=3,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "Could not open review item for held requirement %s",
                            requirement_pk,
                        )
                    return
                # A broker outage here must not 500 the student - the
                # requirement is saved and stays QUEUED, and
                # requeue_stuck_requirement_distributions (Celery beat)
                # picks it up later.
                try:
                    process_requirement_leads.delay(requirement_pk)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Could not enqueue lead distribution for requirement %s - "
                        "left QUEUED for the retry sweep.",
                        requirement_pk,
                    )

            transaction.on_commit(_enqueue_distribution)

        try:
            RequirementVelocityService.note_abandonment(request.user)
        except Exception:  # noqa: BLE001 - a risk-signal write must not break the post
            logger.exception("note_abandonment failed (non-fatal)")

        logger.info(
            "Student requirement created: %s (subject=%s) by %s - distribution %s",
            requirement.id,
            requirement.subject.name,
            request.user.email,
            target_status,
        )

        return APIResponse.success(
            data=StudentRequirementSerializer(requirement).data,
            message=(
                "Requirement submitted. We're matching you with teachers now - "
                "leads will appear on your dashboard shortly."
            ),
            http_status=status.HTTP_202_ACCEPTED,
            distribution_status=target_status,
        )


@extend_schema(tags=["Student Requirements"])
class StudentRequirementDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve one of the authenticated student's own
    requirements.
    PUT/PATCH: Update it - blocked once a teacher has unlocked its
    contact details (see StudentRequirementWriteSerializer.validate),
    regardless of `status` (status alone flips to MATCHED the moment a
    teacher is merely soft-matched, long before anyone unlocks anything).
    DELETE: Soft-delete it (withdraw the requirement).
    """

    lookup_field = "id"

    def get_queryset(self):
        # Scoped to the requesting student's own requirements only -
        # attempting to access another student's requirement id
        # correctly returns 404, not 403, avoiding leaking whether
        # that id exists at all.
        if getattr(self, "swagger_fake_view", False):
            return StudentRequirement.objects.none()
        return _with_unlock_annotation(
            StudentRequirement.objects.filter(student=self.request.user).prefetch_related(
                "schedule_preferences", "preferred_languages__language"
            )
        )

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return StudentRequirementWriteSerializer
        return StudentRequirementSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return APIResponse.success(data=StudentRequirementSerializer(instance).data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = StudentRequirementWriteSerializer(
            instance, data=request.data, partial=partial, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        requirement = serializer.save()

        logger.info(
            "Student requirement updated: %s by %s", requirement.id, request.user.email
        )

        return APIResponse.success(
            data=StudentRequirementSerializer(requirement).data,
            message="Requirement updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        requirement_id = instance.id
        instance.delete()  # soft-delete

        logger.info(
            "Student requirement withdrawn: %s by %s",
            requirement_id,
            request.user.email,
        )

        return APIResponse.no_content(message="Requirement withdrawn successfully.")


def _get_own_requirement_or_raise(request, requirement_id):
    """
    Shared helper: fetches a StudentRequirement scoped to the
    requesting student, raising 404 (not 403) if it doesn't belong
    to them - same security pattern used throughout this project.
    """
    requirement = StudentRequirement.objects.filter(
        id=requirement_id, student=request.user
    ).first()
    if requirement is None:
        raise ResourceNotFoundException(detail="Student requirement not found.")
    return requirement


@extend_schema_view(
    get=extend_schema(
        tags=["Student Schedule Preferences"],
        responses=StudentSchedulePreferenceSerializer(many=True),
        parameters=[
            OpenApiParameter(
                "requirement_id", str, OpenApiParameter.QUERY, required=True
            )
        ],
    ),
    post=extend_schema(
        tags=["Student Schedule Preferences"],
        request=StudentSchedulePreferenceSerializer,
        responses={201: StudentSchedulePreferenceSerializer},
    ),
)
class StudentSchedulePreferenceListCreateView(APIView):
    """
    GET: List schedule preferences for one of the authenticated
    student's own requirements (?requirement_id=<uuid> required).
    POST: Add a new preference to that requirement.
    """

    def get(self, request):
        requirement_id = request.query_params.get("requirement_id")
        if not requirement_id:
            raise ValidationException(
                detail="requirement_id query parameter is required."
            )

        requirement = _get_own_requirement_or_raise(request, requirement_id)
        preferences = requirement.schedule_preferences.all()
        return APIResponse.success(
            data=StudentSchedulePreferenceSerializer(preferences, many=True).data
        )

    def post(self, request):
        from apps.student_requirement.services.preference_service import (
            PreferenceService,
        )

        requirement_id = request.data.get("requirement_id")
        if not requirement_id:
            raise ValidationException(detail="requirement_id is required.")

        requirement = _get_own_requirement_or_raise(request, requirement_id)

        serializer = StudentSchedulePreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        preference = PreferenceService.create_preference(
            requirement, **serializer.validated_data
        )

        logger.info("Schedule preference created for %s", request.user.email)

        return APIResponse.created(
            data=StudentSchedulePreferenceSerializer(preference).data,
            message="Schedule preference added successfully.",
        )


@extend_schema_view(
    patch=extend_schema(
        tags=["Student Schedule Preferences"],
        request=StudentSchedulePreferenceSerializer,
        responses=StudentSchedulePreferenceSerializer,
    ),
    delete=extend_schema(tags=["Student Schedule Preferences"], responses={204: None}),
)
class StudentSchedulePreferenceDetailView(APIView):
    """
    PATCH: Update one of the authenticated student's own preferences.
    DELETE: Remove one of the authenticated student's own preferences.
    """

    def get_object(self, request, preference_id):
        preference = StudentSchedulePreference.objects.filter(
            id=preference_id, student_requirement__student=request.user
        ).first()
        if preference is None:
            raise ResourceNotFoundException(detail="Schedule preference not found.")
        return preference

    def patch(self, request, id):
        from apps.student_requirement.services.preference_service import (
            PreferenceService,
        )

        preference = self.get_object(request, id)
        serializer = StudentSchedulePreferenceSerializer(
            preference, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        updated = PreferenceService.update_preference(
            preference, **serializer.validated_data
        )

        logger.info("Schedule preference updated for %s", request.user.email)

        return APIResponse.success(
            data=StudentSchedulePreferenceSerializer(updated).data,
            message="Schedule preference updated successfully.",
        )

    def delete(self, request, id):
        from apps.student_requirement.services.preference_service import (
            PreferenceService,
        )

        preference = self.get_object(request, id)
        PreferenceService.delete_preference(preference)

        logger.info("Schedule preference removed for %s", request.user.email)

        return APIResponse.no_content(
            message="Schedule preference removed successfully."
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Student Schedule Preferences"],
        responses=StudentScheduleExceptionSerializer(many=True),
        parameters=[
            OpenApiParameter(
                "requirement_id", str, OpenApiParameter.QUERY, required=True
            )
        ],
    ),
    post=extend_schema(
        tags=["Student Schedule Preferences"],
        request=StudentScheduleExceptionSerializer,
        responses={201: StudentScheduleExceptionSerializer},
    ),
)
class StudentScheduleExceptionListCreateView(APIView):
    """
    GET: List schedule exceptions for one of the student's own
    requirements (?requirement_id=<uuid> required).
    POST: Add a new exception.
    """

    def get(self, request):
        requirement_id = request.query_params.get("requirement_id")
        if not requirement_id:
            raise ValidationException(
                detail="requirement_id query parameter is required."
            )

        requirement = _get_own_requirement_or_raise(request, requirement_id)
        exceptions = requirement.schedule_exceptions.all()
        return APIResponse.success(
            data=StudentScheduleExceptionSerializer(exceptions, many=True).data
        )

    def post(self, request):
        requirement_id = request.data.get("requirement_id")
        if not requirement_id:
            raise ValidationException(detail="requirement_id is required.")

        requirement = _get_own_requirement_or_raise(request, requirement_id)

        serializer = StudentScheduleExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exception = serializer.save(student_requirement=requirement)

        logger.info("Schedule exception created for %s", request.user.email)

        return APIResponse.created(
            data=StudentScheduleExceptionSerializer(exception).data,
            message="Schedule exception added successfully.",
        )


@extend_schema(tags=["Student Schedule Preferences"], responses={204: None})
class StudentScheduleExceptionDetailView(APIView):
    """DELETE: Remove one of the authenticated student's own schedule exceptions."""

    def delete(self, request, id):
        exception = StudentScheduleException.objects.filter(
            id=id, student_requirement__student=request.user
        ).first()
        if exception is None:
            raise ResourceNotFoundException(detail="Schedule exception not found.")

        exception.delete(hard=True)

        logger.info("Schedule exception removed for %s", request.user.email)

        return APIResponse.no_content(
            message="Schedule exception removed successfully."
        )
