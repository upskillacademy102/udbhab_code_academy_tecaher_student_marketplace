"""
Admin/Super-Admin endpoints for reviewing and verifying marketplace
teacher profiles.

    GET  /api/v1/admin/teacher-profiles/                    list + filter
    GET  /api/v1/admin/teacher-profiles/{teacher_id}/       one profile
    POST /api/v1/admin/teacher-profiles/{teacher_id}/verification/   set status

A student's "Find Teachers" search (apps.search) only ever returns
teachers whose ``verification_status == VERIFIED``. Until this feature,
that status could only be changed through the Django admin - so a
teacher who signed up and completed their profile stayed invisible to
students forever. These endpoints let an Admin / Super Admin do the
review from the app itself.

Everything is keyed by ``Teacher.id`` (not TeacherProfile.id) so it
lines up with the existing ``/admin-portal/teachers/{id}/`` frontend
navigation.
"""

import logging

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    PermissionDeniedException,
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.teacher_profile.models import TeacherProfile, VerificationStatus

logger = logging.getLogger("apps.teacher_profile")


class AdminTeacherProfileSerializer(serializers.ModelSerializer):
    """Full review payload - Admin sees the teacher's real contact details."""

    id = serializers.UUIDField(source="teacher_id", read_only=True)
    profile_id = serializers.UUIDField(source="id", read_only=True)
    full_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )
    email = serializers.EmailField(source="teacher.user.email", read_only=True)
    mobile = serializers.CharField(
        source="teacher.user.mobile", read_only=True, allow_null=True
    )
    is_active = serializers.BooleanField(
        source="teacher.user.is_active", read_only=True
    )
    experience_years = serializers.IntegerField(
        source="teacher.experience_years", read_only=True, allow_null=True
    )
    qualification_level = serializers.CharField(
        source="teacher.qualification_level", read_only=True, allow_null=True
    )
    qualification_detail = serializers.CharField(
        source="teacher.qualification_detail", read_only=True, allow_null=True
    )
    bio = serializers.CharField(source="teacher.bio", read_only=True, allow_null=True)
    subjects = serializers.SerializerMethodField()
    languages = serializers.SerializerMethodField()
    cities = serializers.SerializerMethodField()
    weekly_availability_count = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = (
            "id",
            "profile_id",
            "full_name",
            "email",
            "mobile",
            "is_active",
            "headline",
            "teaching_mode",
            "hourly_rate",
            "rating",
            "verification_status",
            "experience_years",
            "qualification_level",
            "qualification_detail",
            "bio",
            "subjects",
            "languages",
            "cities",
            "weekly_availability_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_subjects(self, obj) -> list:
        return [s.name for s in obj.subjects.all()]

    def get_languages(self, obj) -> list:
        return [lang.name for lang in obj.languages.all()]

    def get_cities(self, obj) -> list:
        return [c.name for c in obj.cities.all()]

    def get_weekly_availability_count(self, obj) -> int:
        return sum(1 for w in obj.weekly_availability.all() if w.is_active)


def _base_queryset():
    return (
        TeacherProfile.objects.select_related("teacher", "teacher__user")
        .prefetch_related("subjects", "languages", "cities", "weekly_availability")
        .order_by("-created_at")
    )


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(
    tags=["Teacher Verification"],
    parameters=[
        OpenApiParameter(
            "verification_status",
            str,
            OpenApiParameter.QUERY,
            enum=[c[0] for c in VerificationStatus.choices],
        ),
        OpenApiParameter(
            "search", str, OpenApiParameter.QUERY, description="name / email"
        ),
    ],
    responses=AdminTeacherProfileSerializer(many=True),
)
class AdminTeacherProfileListView(generics.ListAPIView):
    serializer_class = AdminTeacherProfileSerializer
    pagination_class = _Pagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TeacherProfile.objects.none()
        qs = _base_queryset()
        status_param = self.request.query_params.get("verification_status")
        if status_param in dict(VerificationStatus.choices):
            qs = qs.filter(verification_status=status_param)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(teacher__user__first_name__icontains=search)
                | Q(teacher__user__last_name__icontains=search)
                | Q(teacher__user__email__icontains=search)
                | Q(headline__icontains=search)
            )
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return APIResponse.paginated(
                data=serializer.data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        return APIResponse.success(data=serializer.data)


def _get_profile_or_404(teacher_id):
    profile = _base_queryset().filter(teacher_id=teacher_id).first()
    if profile is None:
        raise ResourceNotFoundException(
            detail="This teacher has not created a marketplace profile yet."
        )
    return profile


@extend_schema(tags=["Teacher Verification"], responses=AdminTeacherProfileSerializer)
class AdminTeacherProfileDetailView(APIView):
    def get(self, request, id):
        from apps.trust.services.verification_service import VerificationService

        profile = _get_profile_or_404(id)
        data = AdminTeacherProfileSerializer(profile).data
        # Only the detail view carries the checklist (each row costs a
        # recompute; fine for one profile, too much for the list view).
        data["verification_items"] = VerificationService.snapshot(profile.teacher)[
            "items"
        ]
        return APIResponse.success(data=data)


@extend_schema(
    tags=["Teacher Verification"],
    summary="Set a teacher's marketplace verification status",
    request=inline_serializer(
        "TeacherVerificationRequest",
        {"status": serializers.ChoiceField(choices=VerificationStatus.choices)},
    ),
    responses=AdminTeacherProfileSerializer,
)
class AdminTeacherVerificationView(APIView):
    def post(self, request, id):
        profile = _get_profile_or_404(id)

        new_status = (request.data.get("status") or "").strip().lower()
        valid = dict(VerificationStatus.choices)
        if new_status not in valid:
            raise ValidationException(
                detail=f"status must be one of: {', '.join(valid)}."
            )

        old_status = profile.verification_status
        if new_status == old_status:
            return APIResponse.success(
                data=AdminTeacherProfileSerializer(profile).data,
                message=f"Teacher is already {valid[new_status]}.",
            )

        profile.verification_status = new_status
        profile.save(update_fields=["verification_status", "updated_at"])

        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action=f"teacher.verification.{new_status}",
            target=profile.teacher.user,
            message=(
                f"{request.user.email} set {profile.teacher.user.email}'s "
                f"teacher verification: {old_status} -> {new_status}"
            ),
            old_status=old_status,
            new_status=new_status,
        )
        logger.info(
            "Teacher %s verification %s -> %s by %s",
            profile.teacher.user.email,
            old_status,
            new_status,
            request.user.email,
        )

        return APIResponse.success(
            data=AdminTeacherProfileSerializer(profile).data,
            message=f"Teacher marked {valid[new_status]}.",
        )


@extend_schema(
    tags=["Teacher Verification"],
    summary="Verify / reject one checklist item for a teacher",
    request=inline_serializer(
        "TeacherVerificationItemDecision",
        {
            "status": serializers.ChoiceField(
                choices=["verified", "rejected", "submitted"]
            ),
            "notes": serializers.CharField(required=False, allow_blank=True),
        },
    ),
    responses={
        200: OpenApiResponse(description="`data`: the updated checklist snapshot.")
    },
)
class AdminTeacherVerificationItemView(APIView):
    """POST /api/v1/admin/teacher-profiles/{teacher_id}/verification-items/{key}/"""

    @staticmethod
    def _guard_support_admin(user, profile, key):
        """
        A Support-department admin reaches this route only to record the
        outcome of an onboarding call, so it's limited to the
        ``video_interview`` item, and only for a call that admin accepted
        (they're its ``assigned_admin``). The department scope in
        apps.accounts.api_permissions works per route, not per URL ``key``
        or per object, so it can't express either restriction.
        Verification-department admins and Super Admin are unaffected.
        """
        from apps.accounts.models import UserRole

        dept = getattr(getattr(user, "admin_department", None), "slug", None)
        if user.role != UserRole.ADMIN or dept != "support":
            return
        if key != "video_interview":
            raise PermissionDeniedException(
                detail="Support can only decide the onboarding video call."
            )
        from apps.trust.models import OnboardingCallRequest

        accepted_by_me = OnboardingCallRequest.objects.filter(
            item__teacher=profile.teacher,
            item__key="video_interview",
            assigned_admin=user,
            call_started_at__isnull=False,
        ).exists()
        if not accepted_by_me:
            raise PermissionDeniedException(
                detail="You can only decide a call you accepted."
            )

    def post(self, request, id, key):
        from apps.trust.services.verification_service import VerificationService

        profile = _get_profile_or_404(id)
        status_val = (request.data.get("status") or "").strip().lower()
        if status_val not in ("verified", "rejected", "submitted"):
            raise ValidationException(
                detail="status must be verified, rejected, or submitted."
            )

        self._guard_support_admin(request.user, profile, key)

        VerificationService.set_reviewed_item(
            profile.teacher,
            key,
            status=status_val,
            by=request.user,
            notes=(request.data.get("notes") or "").strip(),
        )

        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action=f"teacher.verification_item.{status_val}",
            target=profile.teacher.user,
            message=f"{request.user.email} set {profile.teacher.user.email}'s '{key}' -> {status_val}",
        )
        return APIResponse.success(
            data=VerificationService.snapshot(profile.teacher),
            message=f"'{key}' marked {status_val}.",
        )
