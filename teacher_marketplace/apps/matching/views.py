"""
Views for the matching app.

NOTE ON RELATIONSHIP TO apps.search (Phase 4): apps.search.views.
TeacherSearchView remains as-is, unmodified - it's a lighter-weight,
optionally schedule-aware browse endpoint with no hard eligibility
gate (results are ranked, not filtered by a strict gate). THIS
app's search view is the new, stricter one implementing Sections
14-18's hard eligibility + business-priority ranking - a genuinely
different contract (rejects ineligible teachers outright, rather
than just scoring them low). Both are kept, intentionally serving
different use cases; apps.search is being left as the "browse
teachers loosely" endpoint from Phase 4, this app's endpoint is the
"give me only genuinely eligible teachers, properly ranked" one.

PHASE 6 UPDATE: subject/language/location are now PLAIN TEXT query
params (subject=math, language=english, pincode=Kolkata-or-700001),
resolved internally via SubjectMatchingService / LanguageMatchingService
/ LocationResolutionService. UUID-based subject_id/language_id params
are no longer accepted, per explicit decision - this is an
intentional breaking change. Everything from candidate querying
onward (eligibility, scoring, ranking, response shape) is unchanged.
"""

import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.filters import SearchFilter
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.matching.models import (
    LanguageAlias,
    LeadAssignment,
    MatchingConfig,
    PincodeLocation,
    SubjectAlias,
)
from apps.matching.serializers import (
    LanguageAliasSerializer,
    LeadAssignmentSerializer,
    MatchingConfigSerializer,
    PincodeLocationSerializer,
    SubjectAliasSerializer,
    TeacherSearchResultSerializer,
)

logger = logging.getLogger("apps.matching")


def _get_teacher_or_raise(request):
    teacher = getattr(request.user, "teacher_profile", None)
    if teacher is None:
        raise ResourceNotFoundException(
            detail="You must create your basic Teacher profile first (POST /api/v1/teachers/me/)."
        )
    return teacher


# ==========================================================
# ELIGIBILITY-GATED SEARCH
# ==========================================================
@extend_schema(
    tags=["Matching"],
    parameters=[
        OpenApiParameter(
            "subject",
            str,
            OpenApiParameter.QUERY,
            required=True,
            description="Plain text, e.g. 'math'",
        ),
        OpenApiParameter(
            "day",
            int,
            OpenApiParameter.QUERY,
            required=True,
            description="ISO weekday 1-7",
        ),
        OpenApiParameter(
            "start_time",
            str,
            OpenApiParameter.QUERY,
            required=True,
            description="HH:MM",
        ),
        OpenApiParameter(
            "end_time", str, OpenApiParameter.QUERY, required=True, description="HH:MM"
        ),
        OpenApiParameter(
            "teaching_mode",
            str,
            OpenApiParameter.QUERY,
            required=True,
            enum=["online", "offline", "both"],
        ),
        OpenApiParameter(
            "language", str, OpenApiParameter.QUERY, description="Plain text (optional)"
        ),
        OpenApiParameter(
            "timezone", str, OpenApiParameter.QUERY, description="IANA tz, default UTC"
        ),
        OpenApiParameter(
            "duration_minutes", int, OpenApiParameter.QUERY, description="default 60"
        ),
        OpenApiParameter(
            "pincode",
            str,
            OpenApiParameter.QUERY,
            description="Pincode OR city name; required for offline/both",
        ),
    ],
    responses=TeacherSearchResultSerializer(many=True),
)
class EligibleTeacherSearchView(APIView):
    """
    GET: Returns ONLY genuinely eligible teachers (hard gate per
    Sections 14/15), ranked per Section 32's relevance-then-
    business-priority formula, each with a transparent explanation.

    Required query params: subject (plain text, e.g. "math"), day,
    start_time, end_time, teaching_mode.
    Optional: language (plain text, e.g. "english"), timezone,
    duration_minutes, pincode (plain text - accepts either a real
    pincode like "700001" OR a city name like "Kolkata"; required
    if teaching_mode is offline/both).

    Access control is centralised (route ``matching:eligible-search``):
    authentication required; Student + Admin + Super Admin only.
    """

    def get(self, request):
        from datetime import time as time_cls

        from apps.lead_engine.services.time_compatibility_service import TimeSlot
        from apps.matching.services.eligibility_service import EligibilityService
        from apps.matching.services.language_matching_service import (
            LanguageMatchingService,
        )
        from apps.matching.services.location_matching_service import (
            LocationMatchingService,
        )
        from apps.matching.services.location_resolution_service import (
            LocationResolutionService,
        )
        from apps.matching.services.match_score_service import MatchScoreService
        from apps.matching.services.subject_matching_service import (
            SubjectMatchingService,
        )
        from apps.matching.services.teacher_ranking_service import TeacherRankingService
        from apps.teacher_profile.models import TeacherProfile, TeachingMode

        params = request.query_params

        # ------------------------------------------------------------
        # STEP 1: Resolve plain-text subject/language BEFORE anything
        # else runs. This is the ONLY new step - everything after
        # this block is unchanged from before this patch.
        # ------------------------------------------------------------
        subject_text = params.get("subject")
        if not subject_text:
            raise ValidationException(detail="subject is required.")

        subject_result = SubjectMatchingService.match_by_text(
            subject_text, viewer=request.user
        )
        if not subject_result.is_eligible or subject_result.matched_subject is None:
            raise ValidationException(
                detail=f"Subject '{subject_text}' not recognized. Please check the spelling."
            )
        subject = subject_result.matched_subject

        language_id = None
        language_text = params.get("language")
        if language_text:
            language_result = LanguageMatchingService.match_by_text(
                language_text, viewer=request.user
            )
            if (
                not language_result.is_eligible
                or language_result.matched_subject is None
            ):
                raise ValidationException(
                    detail=f"Language '{language_text}' not recognized. Please check the spelling."
                )
            language_id = language_result.matched_subject.id

        # ------------------------------------------------------------
        # STEP 2: everything below is EXACTLY what existed before -
        # day/time/duration/teaching_mode parsing, candidate query,
        # eligibility loop, ranking, response building. Only
        # `subject` and `language_id` (now resolved above, not read
        # directly from params as UUIDs) are new inputs into this
        # unchanged logic.
        # ------------------------------------------------------------
        try:
            day = int(params["day"])
            start_time = time_cls.fromisoformat(params["start_time"])
            end_time = time_cls.fromisoformat(params["end_time"])
            tz = params.get("timezone", "UTC")
            duration = int(params.get("duration_minutes", 60))
            teaching_mode = params.get("teaching_mode", TeachingMode.ONLINE)
        except (KeyError, ValueError):
            raise ValidationException(
                detail="day, start_time, end_time, and teaching_mode are required and must be valid."
            )

        student_slot = TimeSlot(
            day_of_week=day, start_time=start_time, end_time=end_time, timezone=tz
        )

        from apps.trust.matching_support import apply_teacher_gate

        candidates = (
            apply_teacher_gate(TeacherProfile.objects.filter(subjects=subject))
            .select_related("teacher", "teacher__user")
            .prefetch_related("subjects", "languages", "weekly_availability")
            .distinct()
        )
        if language_id:
            candidates = candidates.filter(languages__id=language_id)

        # ------------------------------------------------------------
        # STEP 3: location - "pincode" param accepts EITHER a real
        # pincode OR a city name, via LocationResolutionService.
        # City-name matches are geocoded to a representative centroid
        # (cached, see PincodeGeocodingService.get_or_geocode_city),
        # so pincode_location is populated - and PostGIS radius
        # matching runs correctly - for BOTH input styles. This
        # replaces the old direct PincodeLocation.objects.filter(
        # pincode=pincode) lookup.
        # ------------------------------------------------------------
        location_results = {}
        if teaching_mode in (TeachingMode.OFFLINE, TeachingMode.BOTH):
            location_text = params.get("pincode")
            if not location_text:
                raise ValidationException(
                    detail="pincode (or city name) is required for offline/both teaching mode search."
                )

            location_result = LocationResolutionService.resolve(location_text)
            pincode_location = location_result.pincode_location

            if pincode_location is not None:
                candidate_pincode_ids = {
                    c.id: c.teacher.pincode_location_id
                    for c in candidates
                    if c.teacher.pincode_location_id is not None
                }
                if candidate_pincode_ids:
                    location_results = (
                        LocationMatchingService.find_eligible_teacher_ids(
                            pincode_location, candidate_pincode_ids
                        )
                    )

        # ------------------------------------------------------------
        # STEP 4: eligibility + scoring loop - UNCHANGED from before.
        # ------------------------------------------------------------
        # Plain object, not a `class _FakeReq` block: a class body that does
        # `teaching_mode = teaching_mode` treats the name as a class-local and
        # raises NameError on the right-hand read (the classic x = x shadow).
        class _FakeReq:
            pass

        fake_requirement = _FakeReq()
        fake_requirement.subject_id = subject.id
        # This endpoint is an ad-hoc param search, not driven by a real
        # StudentRequirement - "no language param" and "any language is
        # fine" are the same thing here, so no_language_preference stays
        # False and an empty id list already means "match everyone" (see
        # LanguageMatchingService.match_by_ids).
        fake_requirement.preferred_language_ids = [language_id] if language_id else []
        fake_requirement.no_language_preference = False
        fake_requirement.class_duration_minutes = duration
        fake_requirement.teaching_mode = teaching_mode

        from apps.matching.services.config_service import get_config

        matching_config = get_config()  # fetched once, not per candidate

        eligible_scored = []
        for profile in candidates:
            teacher_slots = [
                TimeSlot(
                    day_of_week=w.day_of_week,
                    start_time=w.start_time,
                    end_time=w.end_time,
                    timezone=w.timezone,
                )
                for w in profile.weekly_availability.all()
                if w.is_active
            ]

            result = EligibilityService.check_teacher_eligibility(
                teacher_profile=profile,
                requirement=fake_requirement,
                teacher_slots=teacher_slots,
                config=matching_config,
                student_slots=[student_slot],
                location_precomputed=location_results.get(profile.id),
            )
            if result.is_eligible:
                relevance = MatchScoreService.compute(result)
                eligible_scored.append(
                    {
                        "teacher_profile": profile,
                        "relevance": relevance,
                        "eligibility": result,
                    }
                )

        from apps.subscriptions.services import SubscriptionService

        plan_by_teacher_id = SubscriptionService.get_effective_plans(
            {e["teacher_profile"].teacher_id for e in eligible_scored}
        )
        ranked = TeacherRankingService.rank(
            eligible_scored, plan_by_teacher_id=plan_by_teacher_id
        )

        # ------------------------------------------------------------
        # STEP 5: response building - UNCHANGED from before.
        # ------------------------------------------------------------
        results = []
        for candidate in ranked:
            profile = candidate.teacher_profile
            matched_entry = next(
                e for e in eligible_scored if e["teacher_profile"].id == profile.id
            )
            eligibility = matched_entry["eligibility"]

            results.append(
                {
                    "teacher_id": str(profile.teacher.id),
                    "teacher_name": profile.teacher.user.get_full_name(),
                    "subjects": [s.name for s in profile.subjects.all()],
                    "languages": [lang.name for lang in profile.languages.all()],
                    "rating": float(profile.rating),
                    "experience_years": profile.years_of_experience or 0,
                    "teaching_mode": profile.teaching_mode,
                    "hourly_rate": profile.hourly_rate,
                    "is_verified": profile.is_verified,
                    "match_percentage": candidate.relevance.overall,
                    "explanation": {
                        "subject_matched": eligibility.subject_result.is_eligible,
                        "language_matched": eligibility.language_result.is_eligible,
                        "best_matching_day": None,
                        "best_matching_time": (
                            f"{eligibility.time_result['best_start_utc'].strftime('%H:%M')}"
                            if eligibility.time_result.get("best_start_utc")
                            else None
                        ),
                        "distance_km": (
                            eligibility.location_result.distance_km
                            if eligibility.location_result
                            else None
                        ),
                        "within_radius": (
                            eligibility.location_result.is_eligible
                            if eligibility.location_result
                            else None
                        ),
                    },
                }
            )

        serializer = TeacherSearchResultSerializer(results, many=True)
        return APIResponse.success(data=serializer.data)


# ==========================================================
# TEACHER'S OWN LEAD ASSIGNMENTS
# ==========================================================
@extend_schema(tags=["Matching"])
class MyLeadAssignmentsView(generics.ListAPIView):
    serializer_class = LeadAssignmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeadAssignment.objects.none()
        teacher = _get_teacher_or_raise(self.request)
        return LeadAssignment.objects.filter(teacher=teacher).select_related(
            "lead", "lead__student_requirement", "lead__student_requirement__subject"
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)


@extend_schema(
    tags=["Matching"],
    request=None,
    responses=LeadAssignmentSerializer,
    summary="Teacher accepts a lead assignment (stops the cascade for that lead)",
)
class AcceptAssignmentView(APIView):

    def post(self, request, id):
        from apps.matching.services.lead_distribution_service import (
            LeadDistributionService,
        )

        teacher = _get_teacher_or_raise(request)
        assignment = LeadAssignment.objects.filter(id=id, teacher=teacher).first()
        if assignment is None:
            raise ResourceNotFoundException(detail="Lead assignment not found.")

        updated = LeadDistributionService.accept_assignment(assignment)
        return APIResponse.success(
            data=LeadAssignmentSerializer(updated).data,
            message="Lead accepted successfully.",
        )


@extend_schema(
    tags=["Matching"],
    request=None,
    responses=LeadAssignmentSerializer,
    summary="Teacher rejects a lead assignment (may cascade to the next tier)",
)
class RejectAssignmentView(APIView):

    def post(self, request, id):
        from apps.matching.services.lead_distribution_service import (
            LeadDistributionService,
        )

        teacher = _get_teacher_or_raise(request)
        assignment = LeadAssignment.objects.filter(id=id, teacher=teacher).first()
        if assignment is None:
            raise ResourceNotFoundException(detail="Lead assignment not found.")

        updated = LeadDistributionService.reject_assignment(assignment)
        return APIResponse.success(
            data=LeadAssignmentSerializer(updated).data, message="Lead rejected."
        )


# ==========================================================
# ADMIN CRUD - PincodeLocation, SubjectAlias, LanguageAlias, MatchingConfig
# ==========================================================
@extend_schema(tags=["Matching Admin"])
class PincodeLocationListCreateView(generics.ListCreateAPIView):
    queryset = PincodeLocation.objects.all()
    serializer_class = PincodeLocationSerializer
    filter_backends = [SearchFilter]
    search_fields = ["pincode", "city", "state", "country"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        return APIResponse.created(data=PincodeLocationSerializer(obj).data)


@extend_schema(tags=["Matching Admin"])
class SubjectAliasListCreateView(generics.ListCreateAPIView):
    queryset = SubjectAlias.objects.select_related("subject").all()
    serializer_class = SubjectAliasSerializer
    filter_backends = [SearchFilter]
    search_fields = ["alias_text", "subject__name"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        return APIResponse.created(data=SubjectAliasSerializer(obj).data)


@extend_schema(tags=["Matching Admin"])
class LanguageAliasListCreateView(generics.ListCreateAPIView):
    queryset = LanguageAlias.objects.select_related("language").all()
    serializer_class = LanguageAliasSerializer
    filter_backends = [SearchFilter]
    search_fields = ["alias_text", "language__name"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        return APIResponse.created(data=LanguageAliasSerializer(obj).data)


@extend_schema(tags=["Matching Admin"])
class MatchingConfigListCreateView(generics.ListCreateAPIView):
    queryset = MatchingConfig.objects.all()
    serializer_class = MatchingConfigSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        return APIResponse.created(data=MatchingConfigSerializer(obj).data)
