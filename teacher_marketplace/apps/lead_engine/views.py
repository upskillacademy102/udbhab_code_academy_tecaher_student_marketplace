"""
Views for the lead_engine app.

Endpoints (wired up in apps/lead_engine/urls.py, next file):
    GET /api/v1/leads/          -> LeadListView   (teacher's own matching leads)
    GET /api/v1/leads/{id}/      -> LeadDetailView  (marks as viewed on open)

Design note: there is NO create/update/delete endpoint here for
Leads - Lead records are generated exclusively by
apps.lead_engine.services.generate_leads_for_requirement(), called
from student_requirement's view (patched below), never created
directly via this app's API. This app is read-only from the
client's perspective, matching the spec's "Teachers can view
Matching Leads" framing - viewing and marking-as-viewed only.
"""

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import generics
from rest_framework import serializers as drf_serializers
from rest_framework.filters import SearchFilter
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.lead_engine.models import Lead, LeadUnlockHistory, LeadUnlockPricing
from apps.lead_engine.serializers import (
    LeadListSerializer,
    LeadMatchScoreSerializer,
    LeadSerializer,
    LeadUnlockHistorySerializer,
    LeadUnlockPricingSerializer,
    LeadUnlockPricingWriteSerializer,
)
from apps.lead_engine.services.visibility_service import leads_visible_to
from apps.lead_engine.unlock_service import (
    InsufficientBalanceForUnlock,
    unlock_lead_contact,
)
from apps.teacher_profile.models import TeacherProfile
from apps.trust.gates import (
    NotFlaggedAsDuplicate,
    NotRiskSuspended,
    RequireVerifiedEmail,
    RequireVerifiedMobile,
    default_permissions_with,
)

logger = logging.getLogger("apps.lead_engine")


def _get_teacher_profile_or_raise(request):
    """
    Shared helper: resolves the requesting teacher's TeacherProfile,
    raising a clear error if they haven't created one yet. Used by
    both views below to avoid duplicating this traversal + error
    handling twice.
    """
    teacher = getattr(request.user, "teacher_profile", None)
    profile = (
        TeacherProfile.objects.filter(teacher=teacher).first()
        if teacher is not None
        else None
    )
    if profile is None:
        raise ResourceNotFoundException(
            detail=(
                "You must create your marketplace teacher profile first "
                "(POST /api/v1/teachers/profile/) before viewing leads."
            )
        )
    return profile


def _my_rating_map(teacher, leads):
    """{lead_id: verdict} for this teacher's quality ratings on these leads."""
    from apps.trust.models import LeadQualityRating

    return dict(
        LeadQualityRating.objects.filter(
            teacher=teacher, lead__in=[lead_obj.id for lead_obj in leads]
        ).values_list("lead_id", "verdict")
    )


def _unlock_count_map(leads):
    """{lead_id: N} - how many teachers across the WHOLE requirement
    have unlocked it, powering the "N teachers already unlocked this
    lead" badge.

    Each teacher has their OWN separate Lead row for the same
    requirement (unique_lead_per_requirement_teacher_pair), and
    LeadUnlockHistory.lead points at whichever teacher's own row they
    unlocked - never a shared id - so counting by lead_id would only
    ever find 0 or 1 (this teacher's own unlock). The real count has
    to be grouped by student_requirement, then broadcast back to
    every lead that shares it.
    """
    from django.db.models import Count

    requirement_ids = {lead_obj.student_requirement_id for lead_obj in leads}
    counts_by_requirement = dict(
        LeadUnlockHistory.objects.filter(
            lead__student_requirement_id__in=requirement_ids
        )
        .values("lead__student_requirement_id")
        .annotate(n=Count("id"))
        .values_list("lead__student_requirement_id", "n")
    )
    return {
        lead_obj.id: counts_by_requirement.get(lead_obj.student_requirement_id, 0)
        for lead_obj in leads
    }


@extend_schema(tags=["Leads"])
class LeadListView(generics.ListAPIView):
    """
    Lists the authenticated teacher's own matching leads. Uses
    LeadListSerializer (lighter payload) for the list view - full
    detail is available via LeadDetailView.

    Excludes direct offers ("Learn with this teacher" picks) - those
    live exclusively in the Offers tab (LeadOffersView) so a teacher
    isn't asked to spot one gold-glow-worthy card mixed into their
    ordinary matched-lead list.
    """

    serializer_class = LeadListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Lead.objects.none()
        profile = _get_teacher_profile_or_raise(self.request)
        return (
            leads_visible_to(profile)
            .exclude(assignments__is_direct=True)
            .select_related(
                "student_requirement",
                "student_requirement__subject",
                "student_requirement__city",
                "student_requirement__student",
            )
        )

    def list(self, request, *args, **kwargs):
        profile = _get_teacher_profile_or_raise(request)
        queryset = list(self.filter_queryset(self.get_queryset()))
        ctx = {
            "my_ratings": _my_rating_map(profile.teacher, queryset),
            "unlock_counts": _unlock_count_map(queryset),
        }
        serializer = LeadListSerializer(queryset, many=True, context=ctx)
        return APIResponse.success(data=serializer.data)


@extend_schema(tags=["Leads"], summary="Direct offers - students who picked this teacher directly")
class LeadOffersView(generics.ListAPIView):
    """
    GET /api/v1/leads/offers/

    The repurposed "Offers" tab: exclusively direct "Learn with this
    teacher" picks (is_direct=True) - never expire, gold nav-glow
    while any are pending. The general subscription/distance cascade
    lives in the ordinary Leads tab (LeadListView) instead.
    """

    serializer_class = LeadListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Lead.objects.none()
        profile = _get_teacher_profile_or_raise(self.request)
        return (
            leads_visible_to(profile)
            .filter(assignments__is_direct=True)
            .select_related(
                "student_requirement",
                "student_requirement__subject",
                "student_requirement__city",
                "student_requirement__student",
            )
        )

    def list(self, request, *args, **kwargs):
        profile = _get_teacher_profile_or_raise(request)
        queryset = list(self.filter_queryset(self.get_queryset()))
        # No "unlock_counts" here: every lead in this view is a direct offer
        # (is_direct=True, exactly one teacher ever assigned), so the count
        # could only ever be this same teacher counting themselves - the
        # "N teachers already unlocked this lead" badge reads as competitive
        # pressure from OTHER teachers, which structurally can't exist here.
        ctx = {"my_ratings": _my_rating_map(profile.teacher, queryset)}
        serializer = LeadListSerializer(queryset, many=True, context=ctx)
        return APIResponse.success(data=serializer.data)


@extend_schema(
    tags=["Leads"],
    summary="Leads this teacher unlocked but has not rated yet",
    responses={200: OpenApiResponse(description="`data`: {count, results}")},
)
class PendingRatingsView(generics.ListAPIView):
    """
    GET: every lead the teacher has unlocked and not yet rated for quality.
    Drives the "you have N leads to rate" nudge - honest lead feedback is
    what protects every teacher from fake leads.
    """

    serializer_class = LeadListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Lead.objects.none()
        from apps.trust.models import LeadQualityRating

        profile = _get_teacher_profile_or_raise(self.request)
        rated_lead_ids = LeadQualityRating.objects.filter(
            teacher=profile.teacher
        ).values_list("lead_id", flat=True)
        return (
            Lead.objects.filter(
                teacher_profile=profile,
                contact_unlocked=True,
            )
            .exclude(id__in=rated_lead_ids)
            .select_related(
                "student_requirement",
                "student_requirement__subject",
                "student_requirement__city",
                "student_requirement__student",
            )
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        queryset = list(self.get_queryset())
        self._ensure_reminders(queryset)
        serializer = LeadListSerializer(queryset, many=True)
        return APIResponse.success(
            data={"count": len(queryset), "results": serializer.data}
        )

    @staticmethod
    def _ensure_reminders(leads):
        """
        Fires the LEAD_REVIEW_PENDING notification (in-app + email) for any
        of these still-unrated leads that hasn't already gotten one - so a
        teacher who unlocks a lead and leaves without rating it gets an
        actual notification, not just a page they can scroll past. Runs as
        a side effect of every pending-ratings check (this view is what
        both the SPA-wide review gate and the leads list poll), so it
        fires as soon as anything asks "does this teacher owe a rating?" -
        not tied to one specific call site that could be skipped or
        refactored away.
        """
        if not leads:
            return
        from apps.notifications.models import Notification, NotificationEvent
        from apps.notifications.services import NotificationService

        lead_ids = [str(lead_obj.id) for lead_obj in leads]
        already_notified = set(
            Notification.objects.filter(
                event=NotificationEvent.LEAD_REVIEW_PENDING,
                reference_id__in=lead_ids,
            ).values_list("reference_id", flat=True)
        )
        for lead_obj in leads:
            if str(lead_obj.id) not in already_notified:
                NotificationService.lead_review_pending(lead_obj)


@extend_schema(
    tags=["Leads"],
    summary="CSV export of this teacher's unlocked leads",
    responses={200: OpenApiResponse(description="text/csv attachment")},
)
class LeadExportView(APIView):
    """
    GET: streams a CSV of every lead this teacher has unlocked, contact
    details included - the same unlock-gated data already shown on their
    dashboard/leads list, just downloadable. Never includes a lead
    that isn't contact_unlocked, for the same reason every other surface
    in this app withholds it: unlocking is what pays for that visibility.
    """

    def get(self, request):
        import csv

        from django.http import HttpResponse

        profile = _get_teacher_profile_or_raise(request)
        leads = (
            Lead.objects.filter(teacher_profile=profile, contact_unlocked=True)
            .select_related(
                "student_requirement",
                "student_requirement__subject",
                "student_requirement__city",
                "student_requirement__student",
            )
            .order_by("-created_at")
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="leads.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["Subject", "Mode", "City", "Student name", "Phone", "Email", "Status", "Unlocked at"]
        )
        for lead in leads:
            req = lead.student_requirement
            writer.writerow(
                [
                    req.subject.name,
                    req.teaching_mode,
                    req.city.name if req.city else "",
                    req.student.get_full_name(),
                    req.student.mobile,
                    req.student.email,
                    lead.status,
                    lead.created_at.isoformat(),
                ]
            )
        return response


@extend_schema(tags=["Leads"], responses=LeadSerializer)
class LeadDetailView(APIView):
    """
    GET: Retrieve full details of one of the authenticated
    teacher's own leads, and mark it as viewed (first view only -
    see Lead.mark_viewed()). Contact details remain masked
    regardless (see LeadSerializer).
    """

    def get_object(self, request, lead_id):
        profile = _get_teacher_profile_or_raise(request)
        lead = (
            leads_visible_to(profile)
            .filter(id=lead_id)
            .select_related(
                "student_requirement",
                "student_requirement__subject",
                "student_requirement__city",
                "student_requirement__student",
            )
            .prefetch_related("student_requirement__preferred_languages__language")
            .first()
        )
        if lead is None:
            # Scoped to this teacher's own leads only - a lead
            # belonging to another teacher correctly 404s here
            # rather than leaking its existence via a 403.
            raise ResourceNotFoundException(detail="Lead not found.")
        return lead

    @extend_schema(summary="Get lead details (marks as viewed)")
    def get(self, request, id):
        lead = self.get_object(request, id)
        lead.mark_viewed()

        logger.info("Lead %s viewed by teacher %s", lead.id, request.user.email)

        from apps.matching.models import LeadAssignment

        profile = _get_teacher_profile_or_raise(request)
        is_direct = LeadAssignment.objects.filter(
            lead__student_requirement=lead.student_requirement,
            teacher=profile.teacher,
            is_direct=True,
        ).exists()

        # Every teacher's own Lead row across this requirement, not just
        # this one - see _unlock_count_map's docstring for why. Skipped for
        # a direct offer: is_direct means exactly one teacher was ever
        # assigned, so this would only ever count that same teacher
        # unlocking their own lead - the "N teachers already unlocked this
        # lead" badge reads as competitive pressure from OTHER teachers,
        # which structurally can't exist on a direct offer.
        unlocked_count = None
        if not is_direct:
            unlocked_count = LeadUnlockHistory.objects.filter(
                lead__student_requirement=lead.student_requirement
            ).count()
        ctx = {
            "request": request,
            "unlocked_count": unlocked_count,
            "is_direct_offer": is_direct,
        }
        return APIResponse.success(data=LeadSerializer(lead, context=ctx).data)


# ==========================================================
# UNLOCK LEAD (STEP 1 / STEP 2 logic - see unlock_service.py)
# ==========================================================
@extend_schema(
    tags=["Leads"],
    request=inline_serializer(
        "UnlockLeadRequest", {"lead_id": drf_serializers.UUIDField()}
    ),
    responses={
        200: OpenApiResponse(
            description="`data`: {lead, is_free_unlock, tokens_deducted}."
        )
    },
)
class UnlockLeadView(APIView):
    """
    POST: Unlocks a lead's student contact details for the
    authenticated teacher, per the spec's exact Lead Unlock Logic
    (free quota first, then token deduction, then insufficient-
    balance rejection). See apps.lead_engine.unlock_service for the
    full workflow.

    Request body: {"lead_id": "<uuid>"}
    """

    # All four gates are no-ops while their feature flags are OFF (default).
    permission_classes = default_permissions_with(
        RequireVerifiedEmail,
        RequireVerifiedMobile,
        NotFlaggedAsDuplicate,
        NotRiskSuspended,
    )

    def post(self, request):
        profile = _get_teacher_profile_or_raise(request)
        teacher = profile.teacher

        lead_id = request.data.get("lead_id")
        if not lead_id:
            raise ValidationException(detail="lead_id is required.")

        try:
            lead = (
                leads_visible_to(profile)
                .select_related(
                    "teacher_profile",
                    "student_requirement",
                    "student_requirement__subject",
                    "student_requirement__student",
                )
                .get(id=lead_id)
            )
        except Lead.DoesNotExist:
            raise ResourceNotFoundException(detail="Lead not found.")

        try:
            result = unlock_lead_contact(teacher, lead)
        except InsufficientBalanceForUnlock:
            # Re-raise as-is - the custom exception handler already
            # produces a clean 400 with error_code
            # "INSUFFICIENT_BALANCE_FOR_UNLOCK", which the frontend
            # can key off of specifically to show a "Buy tokens"
            # prompt, per the spec's "Prompt User: Purchase Token
            # Package" requirement.
            raise

        logger.info(
            "Lead %s unlocked by %s (free=%s, tokens=%d)",
            lead.id,
            request.user.email,
            result.is_free_unlock,
            result.tokens_deducted,
        )

        return APIResponse.success(
            data={
                "lead": LeadSerializer(
                    result.lead, context={"request": request}
                ).data,
                "is_free_unlock": result.is_free_unlock,
                "tokens_deducted": result.tokens_deducted,
            },
            message=(
                "Lead unlocked successfully using a free lead credit."
                if result.is_free_unlock
                else f"Lead unlocked successfully. {result.tokens_deducted} tokens deducted."
            ),
        )


# ==========================================================
# RATE A LEAD (lead-quality feedback)
# ==========================================================
@extend_schema(
    tags=["Leads"],
    summary="Rate an unlocked lead: genuine / unreachable / fake",
    request=drf_serializers.Serializer,
    responses={200: OpenApiResponse(description="Rating recorded.")},
)
class LeadRateView(APIView):
    """
    POST /api/v1/leads/{id}/rate/  body: {"verdict": "...", "note": "..."}

    Only a lead the teacher has unlocked can be rated. When enough
    independent teachers rate a student's leads fake / unreachable, those
    teachers' unlock tokens are refunded and the student is risk-flagged
    (apps.trust.LeadQualityService).
    """

    def post(self, request, id):
        profile = _get_teacher_profile_or_raise(request)
        lead = (
            Lead.objects.filter(id=id, teacher_profile=profile)
            .select_related(
                "teacher_profile", "student_requirement", "student_requirement__student"
            )
            .first()
        )
        if lead is None:
            raise ResourceNotFoundException(detail="Lead not found.")

        from apps.trust.services.lead_quality_service import LeadQualityService

        rating = LeadQualityService.rate(
            teacher=profile.teacher,
            lead=lead,
            verdict=str(request.data.get("verdict") or "").strip().lower(),
            note=str(request.data.get("note") or "").strip(),
        )
        logger.info(
            "Lead %s rated '%s' by %s", lead.id, rating.verdict, request.user.email
        )
        return APIResponse.success(
            data={"verdict": rating.verdict},
            message="Thanks - your feedback helps keep leads honest.",
        )


@extend_schema(tags=["Leads"], responses={200: OpenApiResponse(description="`data`: {status}")})
class LeadRejectView(APIView):
    """
    POST /api/v1/leads/{id}/reject/

    Lets a teacher permanently decline a lead they have NOT unlocked
    yet - once contact is unlocked, they must review it instead (see
    LeadRateView/PendingRatingsView), never reject it. Rejecting
    releases any open LeadAssignment turn immediately, so
    LeadDistributionService can move on to the next candidate rather
    than waiting for the response window to time out.
    """

    def post(self, request, id):
        from django.utils import timezone

        from apps.lead_engine.models import LeadStatus
        from apps.matching.models import AssignmentStatus, LeadAssignment
        from apps.matching.services.lead_distribution_service import (
            LeadDistributionService,
        )

        profile = _get_teacher_profile_or_raise(request)
        lead = leads_visible_to(profile).filter(id=id).first()
        if lead is None:
            raise ResourceNotFoundException(detail="Lead not found.")

        if lead.contact_unlocked:
            raise ValidationException(
                detail="You've already unlocked this lead - review it instead of rejecting it."
            )
        # No separate "already rejected" check: leads_visible_to() already
        # excludes REJECTED leads, so a repeat call 404s above instead.

        lead.status = LeadStatus.REJECTED
        lead.rejected_at = timezone.now()
        lead.save(update_fields=["status", "rejected_at", "updated_at"])

        # lead__student_requirement, not lead= - LeadAssignment.lead
        # always anchors to one canonical Lead per requirement, even
        # for a non-canonical offered teacher's own assignment (see
        # visibility_service's docstring for why).
        assignment = LeadAssignment.objects.filter(
            lead__student_requirement=lead.student_requirement,
            teacher=profile.teacher,
            status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
        ).first()
        if assignment is not None:
            is_direct = assignment.is_direct
            LeadDistributionService.reject_assignment(assignment)
            if is_direct:
                from apps.notifications.services import NotificationService

                NotificationService.direct_offer_declined(lead)

        logger.info("Lead %s rejected by teacher %s", lead.id, request.user.email)

        return APIResponse.success(
            data={"status": lead.status}, message="Lead rejected."
        )


# ==========================================================
# MY UNLOCK HISTORY
# ==========================================================
@extend_schema(tags=["Leads"])
class MyUnlockHistoryView(generics.ListAPIView):
    """
    GET: The authenticated teacher's own lead unlock history.
    """

    serializer_class = LeadUnlockHistorySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeadUnlockHistory.objects.none()
        profile = _get_teacher_profile_or_raise(self.request)
        return LeadUnlockHistory.objects.filter(teacher=profile.teacher).select_related(
            "lead",
            "lead__student_requirement",
            "lead__student_requirement__subject",
            "teacher",
            "teacher__user",
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return APIResponse.paginated(
                data=serializer.data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)


# ==========================================================
# LEAD UNLOCK PRICING (public read, admin write - Token Pricing
# from the spec, "Admin should configure this")
# ==========================================================
@extend_schema(tags=["Lead Unlock Pricing"])
class LeadUnlockPricingListCreateView(generics.ListCreateAPIView):
    filter_backends = [SearchFilter]
    search_fields = ["tier"]

    def get_queryset(self):
        qs = LeadUnlockPricing.objects.all()
        # Teachers see only the active pricing that applies to them; Admin /
        # Super Admin manage every tier, deactivated rows included.
        if getattr(self.request.user, "is_platform_staff", False):
            return qs
        return qs.filter(is_active=True)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return LeadUnlockPricingWriteSerializer
        return LeadUnlockPricingSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pricing = serializer.save()
        logger.info(
            "Lead unlock pricing created: %s (by %s)", pricing.tier, request.user.email
        )
        return APIResponse.created(
            data=LeadUnlockPricingSerializer(pricing).data,
            message="Pricing created successfully.",
        )


@extend_schema(tags=["Lead Unlock Pricing"])
class LeadUnlockPricingDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = LeadUnlockPricing.objects.all()
    lookup_field = "id"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return LeadUnlockPricingWriteSerializer
        return LeadUnlockPricingSerializer

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        pricing = serializer.save()
        logger.info(
            "Lead unlock pricing updated: %s (by %s)", pricing.tier, request.user.email
        )
        return APIResponse.success(
            data=LeadUnlockPricingSerializer(pricing).data,
            message="Pricing updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        logger.info(
            "Lead unlock pricing soft-deleted: %s (by %s)",
            instance.tier,
            request.user.email,
        )
        return APIResponse.no_content(message="Pricing deleted successfully.")


@extend_schema(tags=["Leads"], responses=LeadMatchScoreSerializer)
class LeadMatchDetailView(APIView):
    """
    GET: Returns the full match score breakdown for one of the
    authenticated teacher's own leads - the spec's
    /api/v1/leads/{id}/matches/ endpoint.
    """

    def get(self, request, id):
        profile = _get_teacher_profile_or_raise(request)

        lead = (
            Lead.objects.filter(id=id, teacher_profile=profile)
            .select_related("match_score")
            .first()
        )
        if lead is None:
            raise ResourceNotFoundException(detail="Lead not found.")

        match_score = getattr(lead, "match_score", None)
        if match_score is None:
            raise ResourceNotFoundException(
                detail="No match score is available for this lead (it may predate the matching engine update)."
            )

        return APIResponse.success(data=LeadMatchScoreSerializer(match_score).data)


@extend_schema(
    tags=["Teachers"],
    parameters=[
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
            "timezone", str, OpenApiParameter.QUERY, description="IANA tz, default UTC"
        ),
        OpenApiParameter(
            "duration_minutes", int, OpenApiParameter.QUERY, description="default 60"
        ),
    ],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Best overlapping slot + time score.",
        )
    },
)
class TeacherBestSlotsView(APIView):
    """
    GET: Given a teacher id and a set of preferred slots (passed as
    query parameters), returns the best overlapping schedule -
    the spec's /api/v1/teachers/{id}/best-slots/ endpoint.

    Query params:
        day, start_time, end_time, timezone, duration_minutes

    Example:
        ?day=1&start_time=18:00&end_time=20:00&timezone=Asia/Kolkata&duration_minutes=60

    Access control is centralised (route
    ``teacher-best-slots:teacher-best-slots``): authentication required;
    Student + Admin + Super Admin only.
    """

    def get(self, request, id):
        from apps.lead_engine.services.time_compatibility_service import (
            TimeCompatibilityService,
            TimeSlot,
        )

        try:
            teacher_profile = TeacherProfile.objects.select_related(
                "teacher", "teacher__user"
            ).get(teacher_id=id)
        except TeacherProfile.DoesNotExist:
            raise ResourceNotFoundException(detail="Teacher profile not found.")

        try:
            day = int(request.query_params.get("day"))
            start_time_str = request.query_params.get("start_time")
            end_time_str = request.query_params.get("end_time")
            tz = request.query_params.get("timezone", "UTC")
            duration = int(request.query_params.get("duration_minutes", 60))
        except (TypeError, ValueError):
            raise ValidationException(
                detail="day, start_time, end_time, timezone, and duration_minutes query parameters are required."
            )

        from datetime import time as time_cls

        try:
            start_time = time_cls.fromisoformat(start_time_str)
            end_time = time_cls.fromisoformat(end_time_str)
        except (ValueError, TypeError):
            raise ValidationException(
                detail="start_time/end_time must be in HH:MM format."
            )

        student_slot = TimeSlot(
            day_of_week=day, start_time=start_time, end_time=end_time, timezone=tz
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
            required_duration_minutes=duration,
        )

        from apps.teacher_profile.models import DayOfWeek

        best_day_label = (
            DayOfWeek(result["best_day"]).label if result["best_day"] else None
        )

        best_start_local = None
        best_end_local = None
        if result["best_start_utc"] is not None:
            best_start_local = TimeCompatibilityService.convert_utc_to_timezone(
                result["best_start_utc"], tz
            ).time()
            best_end_local = TimeCompatibilityService.convert_utc_to_timezone(
                result["best_end_utc"], tz
            ).time()

        return APIResponse.success(
            data={
                "teacher_id": str(teacher_profile.teacher.id),
                "teacher_name": teacher_profile.teacher.user.get_full_name(),
                "time_score": result["time_score"],
                "is_duration_compatible": result["is_duration_compatible"],
                "best_matching_day": best_day_label,
                "best_matching_start_time": (
                    best_start_local.isoformat() if best_start_local else None
                ),
                "best_matching_end_time": (
                    best_end_local.isoformat() if best_end_local else None
                ),
                "timezone": tz,
            }
        )
