"""
Views for the teacher_profile app.

Endpoints (wired up in apps/teacher_profile/urls.py, next file):
    GET/POST/PUT/PATCH /api/v1/teachers/profile/                    -> TeacherProfileView
    GET/POST            /api/v1/teachers/profile/availability/       -> TeacherAvailabilityListCreateView
    DELETE               /api/v1/teachers/profile/availability/{id}/  -> TeacherAvailabilityDetailView

Design note: this app manages a teacher's OWN profile only.
Browsing/searching OTHER teachers' profiles is handled entirely by
apps.search (built later this phase) - this app has no public
list/detail view for other teachers' profiles, keeping a clean
separation between "manage my own data" (here) and "discover other
teachers" (search app).
"""

import logging

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.teacher_profile.models import TeacherAvailability, TeacherProfile
from apps.teacher_profile.serializers import (
    TeacherAvailabilitySerializer,
    TeacherProfileSerializer,
    TeacherProfileWriteSerializer,
    TeacherScheduleExceptionSerializer,
    TeacherWeeklyAvailabilitySerializer,
)

logger = logging.getLogger("apps.teacher_profile")


# ==========================================================
# MY MARKETPLACE PROFILE
# ==========================================================
@extend_schema_view(
    get=extend_schema(tags=["Teacher Profile"], responses=TeacherProfileSerializer),
    post=extend_schema(
        tags=["Teacher Profile"],
        request=TeacherProfileWriteSerializer,
        responses={201: TeacherProfileSerializer},
    ),
    put=extend_schema(
        tags=["Teacher Profile"],
        request=TeacherProfileWriteSerializer,
        responses=TeacherProfileSerializer,
    ),
    patch=extend_schema(
        tags=["Teacher Profile"],
        request=TeacherProfileWriteSerializer,
        responses=TeacherProfileSerializer,
    ),
)
class TeacherProfileView(APIView):
    """
    Lets the authenticated Teacher view, create, or update their
    own TeacherProfile. Requires a Phase 1 Teacher record to
    already exist (created via POST /api/v1/teachers/me/) - this
    profile EXTENDS that record, it doesn't replace it.
    """

    def get_teacher(self, request):
        """
        Fetches (or lazily provisions) the request user's Phase 1
        Teacher record. The marketplace TeacherProfile is a pure
        extension of that record, and every teacher-role user is
        entitled to one, so there is no reason to make the user
        submit a separate "basic details" form first - we create an
        empty Teacher row on demand. The basic-details form then just
        edits that row.
        """
        from apps.accounts.models import UserRole
        from apps.teachers.models import Teacher

        teacher = getattr(request.user, "teacher_profile", None)
        if teacher is not None:
            return teacher

        if getattr(request.user, "role", None) == UserRole.TEACHER:
            teacher, _ = Teacher.objects.get_or_create(user=request.user)
            return teacher

        raise ResourceNotFoundException(
            detail="A teacher account is required to manage a marketplace profile."
        )

    def get_object(self, request):
        teacher = self.get_teacher(request)
        return TeacherProfile.objects.filter(teacher=teacher).first()

    @extend_schema(summary="Get my marketplace teacher profile")
    def get(self, request):
        profile = self.get_object(request)
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found. Create one first."
            )
        return APIResponse.success(data=TeacherProfileSerializer(profile).data)

    @extend_schema(
        summary="Create or update my marketplace teacher profile (upsert)",
        request=TeacherProfileWriteSerializer,
    )
    def post(self, request):
        # Upsert - see TeacherProfileView (apps.teachers) for the reasoning.
        existing = self.get_object(request)
        teacher = self.get_teacher(request)
        serializer = TeacherProfileWriteSerializer(
            existing, data=request.data, partial=existing is not None
        )
        serializer.is_valid(raise_exception=True)
        profile = (
            serializer.save()
            if existing is not None
            else serializer.save(teacher=teacher)
        )

        # Content-leakage scan (Phase 8a/8b) - no-op unless
        # TRUST_ENABLE_CONTACT_LEAKAGE_SCAN is on.
        from apps.trust.services.content_scan_service import ContentScanService
        from apps.trust.services.verification_service import recompute_for_user

        ContentScanService.scan_teacher_profile(profile)
        recompute_for_user(request.user)  # subjects_set may have just flipped

        logger.info(
            "Marketplace teacher profile %s for: %s",
            "updated" if existing is not None else "created",
            request.user.email,
        )

        return APIResponse.success(
            data=TeacherProfileSerializer(profile).data,
            message="Marketplace teacher profile saved.",
            http_status=(
                status.HTTP_200_OK if existing is not None else status.HTTP_201_CREATED
            ),
        )

    @extend_schema(
        summary="Update my marketplace teacher profile",
        request=TeacherProfileWriteSerializer,
    )
    def put(self, request):
        return self._update(request, partial=False)

    @extend_schema(
        summary="Partially update my marketplace teacher profile",
        request=TeacherProfileWriteSerializer,
    )
    def patch(self, request):
        return self._update(request, partial=True)

    def _update(self, request, partial: bool):
        profile = self.get_object(request)
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found. Create one first."
            )

        serializer = TeacherProfileWriteSerializer(
            profile, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        from apps.trust.services.content_scan_service import ContentScanService
        from apps.trust.services.verification_service import recompute_for_user

        ContentScanService.scan_teacher_profile(profile)
        recompute_for_user(request.user)

        logger.info("Marketplace teacher profile updated for: %s", request.user.email)

        return APIResponse.success(
            data=TeacherProfileSerializer(profile).data,
            message="Marketplace teacher profile updated successfully.",
        )


# ==========================================================
# AVAILABILITY
# ==========================================================
@extend_schema_view(
    get=extend_schema(
        tags=["Teacher Profile"], responses=TeacherAvailabilitySerializer(many=True)
    ),
    post=extend_schema(
        tags=["Teacher Profile"],
        request=TeacherAvailabilitySerializer,
        responses={201: TeacherAvailabilitySerializer},
    ),
)
class TeacherAvailabilityListCreateView(APIView):
    """
    GET: List the authenticated teacher's own availability slots.
    POST: Add a new availability slot (day_type + time_slot pair).
    """

    def get_profile(self, request):
        teacher = getattr(request.user, "teacher_profile", None)
        profile = (
            TeacherProfile.objects.filter(teacher=teacher).first()
            if teacher is not None
            else None
        )
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found. Create one first."
            )
        return profile

    @extend_schema(summary="List my availability slots")
    def get(self, request):
        profile = self.get_profile(request)
        slots = profile.availability_slots.all()
        return APIResponse.success(
            data=TeacherAvailabilitySerializer(slots, many=True).data
        )

    @extend_schema(
        summary="Add an availability slot",
        request=TeacherAvailabilitySerializer,
    )
    def post(self, request):
        profile = self.get_profile(request)
        serializer = TeacherAvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        day_type = serializer.validated_data["day_type"]
        time_slot = serializer.validated_data["time_slot"]

        if TeacherAvailability.objects.filter(
            teacher_profile=profile, day_type=day_type, time_slot=time_slot
        ).exists():
            raise ValidationException(
                detail="This availability slot has already been added."
            )

        slot = serializer.save(teacher_profile=profile)

        logger.info(
            "Availability slot added for %s: %s %s",
            request.user.email,
            day_type,
            time_slot,
        )

        return APIResponse.created(
            data=TeacherAvailabilitySerializer(slot).data,
            message="Availability slot added successfully.",
        )


@extend_schema(tags=["Teacher Profile"], responses={204: None})
class TeacherAvailabilityDetailView(APIView):
    """
    DELETE: Remove one of the authenticated teacher's own
    availability slots. Uses hard delete (not soft-delete) since
    availability slots are simple toggle-able selections, not
    records with meaningful audit/history value - unlike Subject/
    Teacher/User records, there's no reason to preserve a deleted
    availability slot.
    """

    def get_object(self, request, slot_id):
        teacher = getattr(request.user, "teacher_profile", None)
        profile = (
            TeacherProfile.objects.filter(teacher=teacher).first()
            if teacher is not None
            else None
        )
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found."
            )

        slot = profile.availability_slots.filter(id=slot_id).first()
        if slot is None:
            raise ResourceNotFoundException(detail="Availability slot not found.")
        return slot

    @extend_schema(summary="Remove an availability slot")
    def delete(self, request, id):
        slot = self.get_object(request, id)
        slot.delete(hard=True)

        logger.info("Availability slot removed for %s", request.user.email)

        return APIResponse.no_content(message="Availability slot removed successfully.")


@extend_schema_view(
    get=extend_schema(
        tags=["Teacher Availability"],
        responses=TeacherWeeklyAvailabilitySerializer(many=True),
    ),
    post=extend_schema(
        tags=["Teacher Availability"],
        request=TeacherWeeklyAvailabilitySerializer,
        responses={201: TeacherWeeklyAvailabilitySerializer},
    ),
)
class TeacherWeeklyAvailabilityListCreateView(APIView):
    """
    GET: List the authenticated teacher's own weekly availability windows.
    POST: Add a new window (validated via AvailabilityService - overlap
    prevention, max-window limit, cache invalidation).
    """

    def get_profile(self, request):
        teacher = getattr(request.user, "teacher_profile", None)
        profile = (
            TeacherProfile.objects.filter(teacher=teacher).first() if teacher else None
        )
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found. Create one first."
            )
        return profile

    def get(self, request):
        profile = self.get_profile(request)
        windows = profile.weekly_availability.all()
        return APIResponse.success(
            data=TeacherWeeklyAvailabilitySerializer(windows, many=True).data
        )

    def post(self, request):
        from apps.teacher_profile.services.availability_service import (
            AvailabilityService,
        )

        profile = self.get_profile(request)
        serializer = TeacherWeeklyAvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        window = AvailabilityService.create_window(profile, **serializer.validated_data)

        from apps.trust.services.verification_service import recompute_for_user

        recompute_for_user(request.user)  # availability_set may have just flipped

        logger.info("Availability window created for %s", request.user.email)

        return APIResponse.created(
            data=TeacherWeeklyAvailabilitySerializer(window).data,
            message="Availability window added successfully.",
        )


@extend_schema_view(
    patch=extend_schema(
        tags=["Teacher Availability"],
        request=TeacherWeeklyAvailabilitySerializer,
        responses=TeacherWeeklyAvailabilitySerializer,
    ),
    delete=extend_schema(tags=["Teacher Availability"], responses={204: None}),
)
class TeacherWeeklyAvailabilityDetailView(APIView):
    """
    PATCH: Update one of the authenticated teacher's own windows.
    DELETE: Remove one of the authenticated teacher's own windows.
    """

    def get_object(self, request, window_id):
        teacher = getattr(request.user, "teacher_profile", None)
        profile = (
            TeacherProfile.objects.filter(teacher=teacher).first() if teacher else None
        )
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found."
            )
        window = profile.weekly_availability.filter(id=window_id).first()
        if window is None:
            raise ResourceNotFoundException(detail="Availability window not found.")
        return window

    def patch(self, request, id):
        from apps.teacher_profile.services.availability_service import (
            AvailabilityService,
        )

        window = self.get_object(request, id)
        serializer = TeacherWeeklyAvailabilitySerializer(
            window, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        updated = AvailabilityService.update_window(window, **serializer.validated_data)

        logger.info("Availability window updated for %s", request.user.email)

        return APIResponse.success(
            data=TeacherWeeklyAvailabilitySerializer(updated).data,
            message="Availability window updated successfully.",
        )

    def delete(self, request, id):
        from apps.teacher_profile.services.availability_service import (
            AvailabilityService,
        )

        window = self.get_object(request, id)
        AvailabilityService.delete_window(window)

        from apps.trust.services.verification_service import recompute_for_user

        recompute_for_user(request.user)

        logger.info("Availability window removed for %s", request.user.email)

        return APIResponse.no_content(
            message="Availability window removed successfully."
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Teacher Availability"],
        responses=TeacherScheduleExceptionSerializer(many=True),
    ),
    post=extend_schema(
        tags=["Teacher Availability"],
        request=TeacherScheduleExceptionSerializer,
        responses={201: TeacherScheduleExceptionSerializer},
    ),
)
class TeacherScheduleExceptionListCreateView(APIView):
    """
    GET: List the authenticated teacher's own schedule exceptions.
    POST: Add a new exception (vacation, holiday, etc.).
    """

    def get_profile(self, request):
        teacher = getattr(request.user, "teacher_profile", None)
        profile = (
            TeacherProfile.objects.filter(teacher=teacher).first() if teacher else None
        )
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found. Create one first."
            )
        return profile

    def get(self, request):
        profile = self.get_profile(request)
        exceptions = profile.schedule_exceptions.all()
        return APIResponse.success(
            data=TeacherScheduleExceptionSerializer(exceptions, many=True).data
        )

    def post(self, request):
        profile = self.get_profile(request)
        serializer = TeacherScheduleExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exception = serializer.save(teacher_profile=profile)

        logger.info("Schedule exception created for %s", request.user.email)

        return APIResponse.created(
            data=TeacherScheduleExceptionSerializer(exception).data,
            message="Schedule exception added successfully.",
        )


@extend_schema(tags=["Teacher Availability"], responses={204: None})
class TeacherScheduleExceptionDetailView(APIView):
    """DELETE: Remove one of the authenticated teacher's own schedule exceptions."""

    def delete(self, request, id):
        teacher = getattr(request.user, "teacher_profile", None)
        profile = (
            TeacherProfile.objects.filter(teacher=teacher).first() if teacher else None
        )
        if profile is None:
            raise ResourceNotFoundException(
                detail="Marketplace teacher profile not found."
            )

        exception = profile.schedule_exceptions.filter(id=id).first()
        if exception is None:
            raise ResourceNotFoundException(detail="Schedule exception not found.")

        exception.delete(hard=True)

        logger.info("Schedule exception removed for %s", request.user.email)

        return APIResponse.no_content(
            message="Schedule exception removed successfully."
        )
