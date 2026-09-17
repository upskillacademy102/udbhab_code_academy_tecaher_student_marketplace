"""
Direct-offer creation: a student's "Learn with this teacher" pick from
that teacher's own profile, bypassing the general matching pool
entirely.

Deliberately kept separate from views.py (StudentRequirementListCreateView)
rather than added as another branch there - the create flow here is
fundamentally different: it skips generate_leads_for_requirement() and
LeadDistributionService.distribute_lead() (which broadcast to every
matching candidate) and instead creates exactly one Lead + one
LeadAssignment(is_direct=True, never_expires=True), scoped to the one
teacher the student picked.

Server-side re-validation, never trust the client-scoped modal alone:
the frontend's "Learn with this teacher" modal limits the student to
this teacher's own subjects/languages/weekly availability, but the
actual eligibility check below (subject taught, language taught if a
preference was given, teaching-mode compatible, and a real time
overlap of at least class_duration_minutes) runs again here against
the teacher's live TeacherProfile/TeacherWeeklyAvailability data.
"""

import logging

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.languages.models import Language
from apps.lead_engine.services.lead_generation_service import (
    _teaching_modes_compatible,
)
from apps.lead_engine.services.time_compatibility_service import (
    TimeCompatibilityService,
    TimeSlot,
)
from apps.student_requirement.models import (
    StudentRequirement,
    StudentRequirementLanguage,
    StudentSchedulePreference,
)
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile
from apps.teachers.models import Teacher

logger = logging.getLogger("apps.student_requirement")


class DirectOfferCreateSerializer(serializers.Serializer):
    offer_teacher_id = serializers.UUIDField()
    subject_id = serializers.UUIDField()
    language_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    no_language_preference = serializers.BooleanField(default=False)
    teaching_mode = serializers.ChoiceField(choices=["online", "offline", "both"])
    day_of_week = serializers.IntegerField(min_value=1, max_value=7)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    timezone = serializers.CharField(max_length=64)
    class_duration_minutes = serializers.ChoiceField(
        choices=[30, 45, 60, 90, 120], default=60
    )

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise serializers.ValidationError(
                f"'{value}' is not a valid IANA timezone name."
            )
        return value

    def validate(self, attrs):
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        if not attrs["no_language_preference"] and not attrs["language_ids"]:
            raise serializers.ValidationError(
                {
                    "language_ids": "Pick at least one of this teacher's languages, "
                    "or set no_language_preference."
                }
            )
        return attrs


@extend_schema(tags=["Student Requirements"])
class DirectOfferCreateView(APIView):
    """
    POST /api/v1/student-requirements/direct-offer/

    Creates a StudentRequirement targeted at exactly one teacher
    (offer_teacher set), plus the single Lead + LeadAssignment that
    lets that teacher unlock/review/reject it through the EXACT same
    machinery as a general-pool lead - no parallel unlock/review
    implementation.
    """

    def post(self, request):
        serializer = DirectOfferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            offer_teacher = Teacher.objects.select_related(
                "marketplace_profile", "user"
            ).get(id=data["offer_teacher_id"])
            teacher_profile = offer_teacher.marketplace_profile
        except (Teacher.DoesNotExist, TeacherProfile.DoesNotExist) as exc:
            raise ResourceNotFoundException(detail="Teacher not found.") from exc

        try:
            subject = Subject.objects.get(id=data["subject_id"])
        except Subject.DoesNotExist as exc:
            raise ResourceNotFoundException(detail="Subject not found.") from exc

        self._validate_against_teacher(teacher_profile, subject, data)

        with transaction.atomic():
            requirement = StudentRequirement.objects.create(
                student=request.user,
                subject=subject,
                teaching_mode=data["teaching_mode"],
                class_duration_minutes=data["class_duration_minutes"],
                no_language_preference=data["no_language_preference"],
                offer_teacher=offer_teacher,
            )
            for rank, language_id in enumerate(data["language_ids"], start=1):
                StudentRequirementLanguage.objects.create(
                    student_requirement=requirement,
                    language_id=language_id,
                    rank=rank,
                )
            StudentSchedulePreference.objects.create(
                student_requirement=requirement,
                day_of_week=data["day_of_week"],
                start_time=data["start_time"],
                end_time=data["end_time"],
                timezone=data["timezone"],
            )

            lead, assignment = self._create_direct_offer(
                requirement, teacher_profile, offer_teacher
            )

        from apps.notifications.services import NotificationService

        NotificationService.direct_offer_received(lead)

        logger.info(
            "Direct offer created: requirement=%s teacher=%s subject=%s",
            requirement.id,
            offer_teacher.id,
            subject.name,
        )
        return APIResponse.success(
            data={"requirement_id": str(requirement.id), "lead_id": str(lead.id)},
            message="Sent. They'll get a notification right away.",
            http_status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _validate_against_teacher(teacher_profile, subject, data):
        if not teacher_profile.subjects.filter(id=subject.id).exists():
            raise ValidationException(
                detail="This teacher doesn't teach that subject."
            )

        if not _teaching_modes_compatible(data["teaching_mode"], teacher_profile.teaching_mode):
            raise ValidationException(
                detail="This teacher doesn't offer that teaching mode."
            )

        if not data["no_language_preference"]:
            taught_ids = set(
                str(lid)
                for lid in teacher_profile.languages.values_list("id", flat=True)
            )
            picked_ids = {str(lid) for lid in data["language_ids"]}
            if not picked_ids.issubset(taught_ids):
                raise ValidationException(
                    detail="This teacher doesn't teach one of the languages you picked."
                )
            if not Language.objects.filter(
                id__in=data["language_ids"]
            ).count() == len(set(data["language_ids"])):
                raise ValidationException(detail="One of those languages doesn't exist.")

        student_slot = TimeSlot(
            day_of_week=data["day_of_week"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            timezone=data["timezone"],
        )
        teacher_slots = [
            TimeSlot(
                day_of_week=w.day_of_week,
                start_time=w.start_time,
                end_time=w.end_time,
                timezone=w.timezone,
            )
            for w in teacher_profile.weekly_availability.filter(is_active=True)
        ]
        result = TimeCompatibilityService.find_best_overlap(
            student_slots=[student_slot],
            teacher_slots=teacher_slots,
            required_duration_minutes=data["class_duration_minutes"],
        )
        if not (result["has_any_overlap"] and result["is_duration_compatible"]):
            raise ValidationException(
                detail="That time doesn't fit this teacher's actual availability."
            )

    @staticmethod
    def _create_direct_offer(requirement, teacher_profile, offer_teacher):
        from apps.lead_engine.models import Lead, LeadMatchScore
        from apps.lead_engine.services.matching_service import MatchingService
        from apps.matching.models import AssignmentStatus, LeadAssignment
        from apps.subscriptions.services import SubscriptionService

        now = timezone.now()
        lead = Lead.objects.create(
            student_requirement=requirement, teacher_profile=teacher_profile
        )
        plan = SubscriptionService.get_effective_plan(offer_teacher)
        score = MatchingService.score_teacher(
            teacher_profile, requirement, effective_plan=plan
        )
        LeadMatchScore.objects.create(lead=lead, **score)
        assignment = LeadAssignment.objects.create(
            lead=lead,
            teacher=offer_teacher,
            subscription_tier=plan.name,
            assignment_stage=1,
            assigned_at=now,
            expires_at=now,  # never read - never_expires=True below
            status=AssignmentStatus.ASSIGNED,
            is_direct=True,
            never_expires=True,
        )
        return lead, assignment
