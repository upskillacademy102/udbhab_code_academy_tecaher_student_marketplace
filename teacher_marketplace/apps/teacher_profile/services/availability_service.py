"""
Availability service for the Teacher Marketplace Platform.

Handles CRUD + validation for TeacherWeeklyAvailability, including:
    - Overlap prevention (deferred from the model layer - see
      TeacherWeeklyAvailability.Meta's UniqueConstraint docstring
      for why this can't be a simple database constraint).
    - The MAX_AVAILABILITY_WINDOWS_PER_TEACHER application limit.
    - Cache invalidation - per the spec's explicit "Invalidate
      cache whenever availability changes" requirement. See
      apps.lead_engine.services.matching_service for the read side
      of this cache (added when we get to the search/matching
      views, to avoid introducing caching before there's a real
      read path that benefits from it).
"""

from django.core.cache import cache
from django.db import transaction

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.teacher_profile.models import (
    MAX_AVAILABILITY_WINDOWS_PER_TEACHER,
    TeacherProfile,
    TeacherWeeklyAvailability,
)


def _availability_cache_key(teacher_profile_id) -> str:
    return f"teacher_availability:{teacher_profile_id}"


class AvailabilityService:

    @staticmethod
    def _windows_overlap(a_start, a_end, b_start, b_end) -> bool:
        return a_start < b_end and b_start < a_end

    @staticmethod
    def _check_no_overlap(
        teacher_profile, day_of_week, start_time, end_time, exclude_id=None
    ):
        """
        Checks the new/updated window against every OTHER active
        window this teacher already has on the same day. Timezone
        is deliberately NOT considered here - overlap-prevention
        operates on the teacher's own locally-stored times for
        their own schedule (comparing a teacher's slots against
        each other is meaningful in their own local clock; cross-
        timezone comparison is only meaningful when comparing
        DIFFERENT people's schedules, which is TimeCompatibilityService's
        job, not this validation's).
        """
        existing = teacher_profile.weekly_availability.filter(
            day_of_week=day_of_week, is_active=True
        )
        if exclude_id is not None:
            existing = existing.exclude(id=exclude_id)

        for window in existing:
            if AvailabilityService._windows_overlap(
                start_time, end_time, window.start_time, window.end_time
            ):
                raise ValidationException(
                    detail=(
                        f"This window overlaps with an existing availability "
                        f"window on {window.get_day_of_week_display()} "
                        f"({window.start_time}-{window.end_time})."
                    )
                )

    @staticmethod
    @transaction.atomic
    def create_window(
        teacher_profile: TeacherProfile, **fields
    ) -> TeacherWeeklyAvailability:
        current_count = teacher_profile.weekly_availability.count()
        if current_count >= MAX_AVAILABILITY_WINDOWS_PER_TEACHER:
            raise ValidationException(
                detail=(
                    f"Maximum of {MAX_AVAILABILITY_WINDOWS_PER_TEACHER} availability "
                    f"windows reached. Remove an existing window before adding a new one."
                )
            )

        AvailabilityService._check_no_overlap(
            teacher_profile,
            fields["day_of_week"],
            fields["start_time"],
            fields["end_time"],
        )

        window = TeacherWeeklyAvailability(teacher_profile=teacher_profile, **fields)
        window.full_clean()  # runs the model's clean() - timezone validity, start<end
        window.save()

        AvailabilityService._invalidate_cache(teacher_profile.id)
        return window

    @staticmethod
    @transaction.atomic
    def update_window(
        window: TeacherWeeklyAvailability, **fields
    ) -> TeacherWeeklyAvailability:
        day_of_week = fields.get("day_of_week", window.day_of_week)
        start_time = fields.get("start_time", window.start_time)
        end_time = fields.get("end_time", window.end_time)

        AvailabilityService._check_no_overlap(
            window.teacher_profile,
            day_of_week,
            start_time,
            end_time,
            exclude_id=window.id,
        )

        for key, value in fields.items():
            setattr(window, key, value)
        window.full_clean()
        window.save()

        AvailabilityService._invalidate_cache(window.teacher_profile_id)
        return window

    @staticmethod
    def delete_window(window: TeacherWeeklyAvailability) -> None:
        teacher_profile_id = window.teacher_profile_id
        window.delete(
            hard=True
        )  # availability windows are simple toggles, not audit data
        AvailabilityService._invalidate_cache(teacher_profile_id)

    @staticmethod
    def _invalidate_cache(teacher_profile_id) -> None:
        cache.delete(_availability_cache_key(teacher_profile_id))

    @staticmethod
    def get_cached_windows(teacher_profile: TeacherProfile):
        """
        Cache-through read used by MatchingService/search - avoids
        re-querying the same teacher's availability repeatedly
        within a single matching pass across many requirements, or
        across concurrent search requests. Cache is invalidated
        immediately on any create/update/delete above, so it can
        never return stale data after a genuine schedule change,
        per the spec's explicit caching requirement.
        """
        key = _availability_cache_key(teacher_profile.id)
        cached = cache.get(key)
        if cached is not None:
            return cached

        windows = list(teacher_profile.weekly_availability.filter(is_active=True))
        cache.set(
            key, windows, timeout=300
        )  # 5 minutes - short TTL as a safety net alongside explicit invalidation
        return windows
