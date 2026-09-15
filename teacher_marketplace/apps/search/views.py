"""
Views for the search app.

Endpoint (wired up in apps/search/urls.py):
    GET /api/v1/search/teachers/

PHASE 4 UPDATE: now accepts optional schedule filters (preferred_day,
preferred_start_time, preferred_end_time, timezone, duration_minutes).
When ALL of these are supplied together, each result is annotated
with a live-computed match_percentage and best_matching_time (via
TimeCompatibilityService, the same engine apps.lead_engine's
MatchingService uses for Lead generation) and results are re-ordered
by that score. When schedule filters are absent, results fall back
to the original Phase 2 ordering (rating/created_at) with no time
scoring - this endpoint intentionally supports BOTH a lightweight
general-browse mode and a schedule-aware mode, since not every
search visit has a specific time in mind yet.

This does NOT create a Lead or a LeadMatchScore row - this is a
lighter-weight, on-demand computation for browsing, distinct from
the persisted, requirement-tied scoring apps.lead_engine performs at
submission time (see that app's matching_service.py module
docstring for the full two-phase performance strategy this search
view also follows: cheap SQL filtering first, expensive time-overlap
math only against the resulting page of candidates, never the full
table).
"""

import django_filters
from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import OrderingFilter

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.core.responses import APIResponse
from apps.teacher_profile.models import TeacherProfile, TeachingMode, VerificationStatus
from apps.teacher_profile.serializers import TeacherProfileSerializer


class TeacherSearchOrderingFilter(OrderingFilter):
    """
    Student-facing sort options for teacher browse. Maps friendly param
    values to real fields and always pushes NULLs (e.g. a teacher who
    hasn't set experience or an hourly rate) to the BOTTOM, whichever
    direction is requested - so "Most experienced" never surfaces a
    teacher with no experience recorded.

    ``?ordering=`` accepts: experience | -experience | rating | -rating |
    price | -price | newest.  With no param the DEFAULT_ORDER below
    applies: rating desc, then **experience desc**, then newest - so a
    plain browse is still experience-aware (experience is the canonical
    tiebreak between rating and the created_at deterministic tiebreak,
    per Section 16 / TeacherRanking_service's priority list), rather than
    falling back to arbitrary creation order when ratings tie (which they
    almost always do until the review system ships).
    """

    ordering_param = "ordering"
    _MAP = {
        "experience": "teacher__experience_years",
        "rating": "rating",
        "price": "hourly_rate",
        "hourly_rate": "hourly_rate",
        "newest": "created_at",
        "created_at": "created_at",
    }
    ordering_fields = tuple(_MAP)

    #: Applied when no ``?ordering=`` is supplied. Kept here (not as
    #: ``view.ordering`` strings) because it needs nulls_last handling
    #: on the nullable experience column.
    DEFAULT_ORDER = (
        F("rating").desc(nulls_last=True),
        F("teacher__experience_years").desc(nulls_last=True),
        F("created_at").desc(),
    )

    def filter_queryset(self, request, queryset, view):
        raw = (request.query_params.get(self.ordering_param) or "").strip()
        if not raw:
            from apps.trust.matching_support import ranking_enabled

            if ranking_enabled():
                # Browse (no explicit sort) surfaces more-verified teachers first.
                return queryset.order_by(
                    F("_vscore").desc(nulls_last=True), *self.DEFAULT_ORDER
                )
            return queryset.order_by(*self.DEFAULT_ORDER)

        exprs = []
        for term in raw.split(","):
            term = term.strip()
            desc = term.startswith("-")
            field = self._MAP.get(term[1:] if desc else term)
            if not field:
                continue
            col = F(field)
            exprs.append(
                col.desc(nulls_last=True) if desc else col.asc(nulls_last=True)
            )

        if not exprs:  # param present but unrecognised - fall back to default
            return queryset.order_by(*self.DEFAULT_ORDER)

        exprs.append(F("created_at").desc())  # deterministic tiebreaker
        return queryset.order_by(*exprs)


class TeacherSearchFilterSet(django_filters.FilterSet):
    """
    Implements every filter criterion the spec lists for teacher
    search, extended in Phase 4 with schedule-related fields.
    """

    subject = django_filters.CharFilter(method="filter_subject_text")
    language = django_filters.CharFilter(method="filter_language_text")
    city = django_filters.CharFilter(method="filter_city_text")

    def filter_subject_text(self, queryset, name, value):
        from apps.matching.services.subject_matching_service import (
            SubjectMatchingService,
        )

        result = SubjectMatchingService.match_by_text(value)
        if not result.is_eligible or result.matched_subject is None:
            return queryset.none()
        return queryset.filter(subjects__id=result.matched_subject.id)

    def filter_language_text(self, queryset, name, value):
        from apps.matching.services.language_matching_service import (
            LanguageMatchingService,
        )

        result = LanguageMatchingService.match_by_text(value)
        if not result.is_eligible or result.matched_subject is None:
            return queryset.none()
        return queryset.filter(languages__id=result.matched_subject.id)

    def filter_city_text(self, queryset, name, value):
        from apps.matching.services.location_resolution_service import (
            LocationResolutionService,
        )

        try:
            result = LocationResolutionService.resolve(value)
        except Exception:
            return queryset.none()
        if result.city is not None:
            return queryset.filter(cities__id=result.city.id)
        return queryset  # pincode-only match not applicable to this browse-search's city M2M

    teaching_mode = django_filters.ChoiceFilter(choices=TeachingMode.choices)

    min_experience = django_filters.NumberFilter(
        field_name="teacher__experience_years", lookup_expr="gte"
    )
    max_experience = django_filters.NumberFilter(
        field_name="teacher__experience_years", lookup_expr="lte"
    )

    min_price = django_filters.NumberFilter(field_name="hourly_rate", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="hourly_rate", lookup_expr="lte")

    min_rating = django_filters.NumberFilter(field_name="rating", lookup_expr="gte")

    verified_only = django_filters.BooleanFilter(method="filter_verified_only")

    class Meta:
        model = TeacherProfile
        fields = [
            "subject",
            "language",
            "city",
            "teaching_mode",
            "min_experience",
            "max_experience",
            "min_price",
            "max_price",
            "min_rating",
            "verified_only",
        ]

    def filter_verified_only(self, queryset, name, value):
        if value:
            return queryset.filter(verification_status=VerificationStatus.VERIFIED)
        return queryset


@extend_schema(tags=["Search"])
class TeacherSearchView(generics.ListAPIView):
    """
    Teacher search. **Authentication required** - access is centralised
    (route ``search:teacher-search``): Student + Admin + Super Admin only.
    Teachers may not use marketplace teacher-search.

    Schedule-aware query params (all optional; activates time scoring).
    Two forms - see _parse_schedule_params:
        preferred_slots - JSON array of {"day","start_time","end_time"}
            for a student free at more than one distinct day+time
            (e.g. Monday 7pm AND Tuesday 8am - each with its own
            time, not one time applied to every day).
        preferred_day / preferred_start_time / preferred_end_time -
            legacy single-slot form, must be supplied TOGETHER.
        timezone (IANA name), duration_minutes (default 60) - shared
        across every slot in one request either way.
    """

    serializer_class = TeacherProfileSerializer
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        TeacherSearchOrderingFilter,
    ]
    filterset_class = TeacherSearchFilterSet
    # Default sort lives on TeacherSearchOrderingFilter.DEFAULT_ORDER
    # (rating desc -> experience desc -> newest); the student can re-sort
    # via the UI (experience / price / newest).
    ordering = ["-rating", "-created_at"]  # referenced only by drf-spectacular

    def get_queryset(self):
        from apps.trust.matching_support import (
            apply_teacher_gate,
            exclude_blocked_teachers,
            ranking_enabled,
        )

        qs = (
            exclude_blocked_teachers(
                apply_teacher_gate(TeacherProfile.objects.all()),
                getattr(self.request, "user", None),
            )
            .select_related("teacher", "teacher__user", "teacher__user__trust_profile")
            .prefetch_related(
                "subjects",
                "languages",
                "cities",
                "availability_slots",
                "weekly_availability",
            )
            .distinct()
        )
        if ranking_enabled():
            from django.db.models import F as _F

            qs = qs.annotate(
                _vscore=_F("teacher__user__trust_profile__verification_score")
            )
        return qs

    def _parse_schedule_params(self, request):
        """
        Returns a list of TimeSlots for the requested preference(s) if
        valid schedule params are present, else None (meaning: fall
        back to non-schedule-aware search). Partial/malformed schedule
        params raise a clean 400 rather than silently ignoring them,
        since a caller who supplied SOME schedule params almost
        certainly intended schedule-aware search and would want to
        know it didn't activate.

        Two ways to specify slots, checked in this order:

        1. `preferred_slots` - a JSON array of {"day", "start_time",
           "end_time"} objects, for a student free at more than one
           distinct day+time (e.g. "Monday 7pm AND Tuesday 8am" - two
           slots with different times, not one time applied to both
           days). `TimeCompatibilityService.find_best_overlap` already
           compares every (student_slot, teacher_slot) combination and
           keeps the best, so this is a thin parsing layer over
           capability that already existed - the single-slot view
           below just never passed more than one element through it.

        2. The legacy single-slot params (`preferred_day`,
           `preferred_start_time`, `preferred_end_time`) - kept
           working exactly as before for existing callers (the
           per-teacher "Can they do your time?" checker, older
           clients), producing a one-element list.

        `timezone` and `duration_minutes` are shared across every slot
        in one request - one student, one clock.
        """
        params = request.query_params
        from datetime import time as time_cls

        from apps.lead_engine.services.time_compatibility_service import TimeSlot

        def _validated_timezone() -> str:
            tz = params.get("timezone", "UTC")
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(tz)
            except Exception:
                raise ValidationException(
                    detail=f"'{tz}' is not a valid IANA timezone name."
                )
            return tz

        raw_slots = params.get("preferred_slots")
        if raw_slots:
            import json

            try:
                parsed = json.loads(raw_slots)
                if not isinstance(parsed, list) or not parsed:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValidationException(
                    detail="preferred_slots must be a non-empty JSON array."
                )

            tz = _validated_timezone()
            slots = []
            for entry in parsed:
                try:
                    day = int(entry["day"])
                    start_time = time_cls.fromisoformat(entry["start_time"])
                    end_time = time_cls.fromisoformat(entry["end_time"])
                except (KeyError, ValueError, TypeError):
                    raise ValidationException(
                        detail="Each preferred_slots entry needs day (1-7), "
                        "start_time and end_time (HH:MM)."
                    )
                slots.append(
                    TimeSlot(
                        day_of_week=day,
                        start_time=start_time,
                        end_time=end_time,
                        timezone=tz,
                    )
                )
            return slots

        provided = [
            params.get("preferred_day"),
            params.get("preferred_start_time"),
            params.get("preferred_end_time"),
        ]
        if not any(provided):
            return None
        if not all(provided):
            raise ValidationException(
                detail=(
                    "preferred_day, preferred_start_time, and preferred_end_time "
                    "must all be supplied together to enable schedule-aware search."
                )
            )

        try:
            day = int(params["preferred_day"])
            start_time = time_cls.fromisoformat(params["preferred_start_time"])
            end_time = time_cls.fromisoformat(params["preferred_end_time"])
        except (ValueError, TypeError):
            raise ValidationException(
                detail="preferred_day must be 1-7, and times must be in HH:MM format."
            )

        tz = _validated_timezone()
        return [
            TimeSlot(
                day_of_week=day, start_time=start_time, end_time=end_time, timezone=tz
            )
        ]

    def list(self, request, *args, **kwargs):
        student_slots = self._parse_schedule_params(request)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        candidates = page if page is not None else list(queryset)

        if student_slots is not None:
            candidates = self._annotate_and_sort_by_time(
                candidates, request, student_slots
            )

        serializer = self.get_serializer(candidates, many=True)
        data = serializer.data

        if student_slots is not None:
            for item, candidate in zip(data, candidates):
                item["match_percentage"] = candidate._match_percentage
                item["best_matching_time"] = candidate._best_matching_time

        if page is not None:
            return APIResponse.paginated(
                data=data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        return APIResponse.success(data=data)

    def _annotate_and_sort_by_time(self, candidates, request, student_slots):
        """
        For each candidate (already a small, paginated page - not
        the full table, per the two-phase performance strategy),
        computes time compatibility against every requested slot
        (find_best_overlap compares all student_slot x teacher_slot
        combinations and keeps the best - a teacher matching ANY one
        of the student's slots scores on that best combination, not
        an average across all of them) and attaches the result as
        transient attributes for the response to read. Sorts the page
        by this score, highest first - this only re-orders WITHIN the
        current page (the underlying SQL ordering already applied
        rating/price sorting before pagination), which is an accepted,
        documented tradeoff: true global sort-by-time-score across the
        entire result set before pagination would require computing
        time scores for every matching teacher up front, which is
        exactly the "expensive full scan" this architecture's
        two-phase strategy is designed to avoid at search-browse scale.
        """
        from apps.lead_engine.services.time_compatibility_service import (
            TimeCompatibilityService,
            TimeSlot,
        )

        duration = int(request.query_params.get("duration_minutes", 60))
        display_tz = student_slots[0].timezone

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
            result = TimeCompatibilityService.find_best_overlap(
                student_slots=student_slots,
                teacher_slots=teacher_slots,
                required_duration_minutes=duration,
            )
            profile._match_percentage = result["time_score"]

            if result["best_start_utc"] is not None:
                start_local = TimeCompatibilityService.convert_utc_to_timezone(
                    result["best_start_utc"], display_tz
                )
                end_local = TimeCompatibilityService.convert_utc_to_timezone(
                    result["best_end_utc"], display_tz
                )
                profile._best_matching_time = f"{start_local.strftime('%A %I:%M %p')} - {end_local.strftime('%I:%M %p')}"
            else:
                profile._best_matching_time = None

        return sorted(candidates, key=lambda p: -p._match_percentage)
