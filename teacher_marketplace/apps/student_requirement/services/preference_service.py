"""
Schedule preference service for the Teacher Marketplace Platform.

Mirrors apps.teacher_profile.services.availability_service.
AvailabilityService exactly in structure and reasoning - see that
file's docstrings for the full explanation of overlap-prevention
logic, cache invalidation strategy, and why full_clean() is called
explicitly. This file exists as a parallel implementation (not a
shared base class) since the two sides, while structurally similar,
operate on genuinely different models with different owning
relationships (TeacherProfile vs StudentRequirement) - a shared
abstraction would add indirection without meaningfully reducing
the amount of code, given how small each method already is.
"""

from django.core.cache import cache
from django.db import transaction

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.student_requirement.models import (
    MAX_PREFERENCE_WINDOWS_PER_REQUIREMENT,
    StudentRequirement,
    StudentSchedulePreference,
)


def _preference_cache_key(requirement_id) -> str:
    return f"student_preferences:{requirement_id}"


class PreferenceService:

    @staticmethod
    def _windows_overlap(a_start, a_end, b_start, b_end) -> bool:
        return a_start < b_end and b_start < a_end

    @staticmethod
    def _check_no_overlap(
        requirement, day_of_week, start_time, end_time, exclude_id=None
    ):
        existing = requirement.schedule_preferences.filter(day_of_week=day_of_week)
        if exclude_id is not None:
            existing = existing.exclude(id=exclude_id)

        for window in existing:
            if PreferenceService._windows_overlap(
                start_time, end_time, window.start_time, window.end_time
            ):
                raise ValidationException(
                    detail=(
                        f"This preference overlaps with an existing preference on "
                        f"{window.get_day_of_week_display()} ({window.start_time}-{window.end_time})."
                    )
                )

    @staticmethod
    @transaction.atomic
    def create_preference(
        requirement: StudentRequirement, **fields
    ) -> StudentSchedulePreference:
        current_count = requirement.schedule_preferences.count()
        if current_count >= MAX_PREFERENCE_WINDOWS_PER_REQUIREMENT:
            raise ValidationException(
                detail=(
                    f"Maximum of {MAX_PREFERENCE_WINDOWS_PER_REQUIREMENT} schedule "
                    f"preferences reached for this requirement."
                )
            )

        PreferenceService._check_no_overlap(
            requirement, fields["day_of_week"], fields["start_time"], fields["end_time"]
        )

        preference = StudentSchedulePreference(
            student_requirement=requirement, **fields
        )
        preference.full_clean()
        preference.save()

        PreferenceService._invalidate_cache(requirement.id)
        return preference

    @staticmethod
    @transaction.atomic
    def update_preference(
        preference: StudentSchedulePreference, **fields
    ) -> StudentSchedulePreference:
        day_of_week = fields.get("day_of_week", preference.day_of_week)
        start_time = fields.get("start_time", preference.start_time)
        end_time = fields.get("end_time", preference.end_time)

        PreferenceService._check_no_overlap(
            preference.student_requirement,
            day_of_week,
            start_time,
            end_time,
            exclude_id=preference.id,
        )

        for key, value in fields.items():
            setattr(preference, key, value)
        preference.full_clean()
        preference.save()

        PreferenceService._invalidate_cache(preference.student_requirement_id)
        return preference

    @staticmethod
    def delete_preference(preference: StudentSchedulePreference) -> None:
        requirement_id = preference.student_requirement_id
        preference.delete(hard=True)
        PreferenceService._invalidate_cache(requirement_id)

    @staticmethod
    def _invalidate_cache(requirement_id) -> None:
        cache.delete(_preference_cache_key(requirement_id))

    @staticmethod
    def get_cached_preferences(requirement: StudentRequirement):
        key = _preference_cache_key(requirement.id)
        cached = cache.get(key)
        if cached is not None:
            return cached

        preferences = list(requirement.schedule_preferences.all())
        cache.set(key, preferences, timeout=300)
        return preferences
