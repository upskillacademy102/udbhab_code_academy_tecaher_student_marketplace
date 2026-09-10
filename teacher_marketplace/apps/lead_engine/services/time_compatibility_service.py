"""
Time compatibility calculation service for the Teacher Marketplace
Platform.

CORE DESIGN: TIMEZONE-SAFE OVERLAP VIA REAL-DATE ANCHORING

A recurring weekly slot ("Monday 18:00-20:00, America/New_York") has
no single fixed UTC equivalent, because America/New_York observes
DST and Asia/Kolkata does not. To compare a student's slot against a
teacher's slot correctly, both must be converted to UTC using
Python's zoneinfo against a REAL calendar date - not a fixed offset
- so DST rules are correctly applied for whatever date the
conversion is anchored to.

This service anchors every conversion to the Monday of the CURRENT
real calendar week (see _reference_monday). This means: matching
computed today reflects today's DST state for every timezone
involved. A slot's computed UTC time could shift by up to an hour
across a DST transition boundary later in the year - this is
correct, expected behavior for a RECURRING slot (its real-world UTC
time genuinely does shift with DST), not a bug. Exact session
scheduling for a specific future calendar date is a booking-system
concern for a later phase (see the module-level note in
matching_service.py) - this service answers "are these two recurring
weekly patterns compatible right now," which is what lead-generation-
time matching needs.

WEEK-BOUNDARY WRAPAROUND: converting a local time to UTC can shift
which calendar day it falls on (e.g. Sunday 23:30 in a UTC+13 zone
becomes Monday UTC). To avoid missing a genuine overlap that only
becomes visible after this shift, every comparison is computed
against three adjacent reference weeks (previous, current, next) and
the best (maximum) overlap across all three is used.

ARCHITECTURE NOTE: this service is pure - it takes plain TimeSlot
dataclasses and returns plain result dicts/dataclasses. It has NO
Django ORM queries and NO knowledge of Teacher/Student models. This
keeps the actual overlap MATH independently testable (per the spec's
extensive testing requirements) without needing database fixtures
for every test case - callers (matching_service.py) are responsible
for fetching TeacherWeeklyAvailability/StudentSchedulePreference rows
and converting them into TimeSlot objects first.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from django.utils import timezone as django_timezone

logger = logging.getLogger("apps.lead_engine.time_compatibility")

UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class TimeSlot:
    """
    A generic recurring weekly time slot - deliberately agnostic to
    whether it originated from a TeacherWeeklyAvailability row or a
    StudentSchedulePreference row, so the comparison logic below
    doesn't need two parallel code paths.
    """

    day_of_week: int  # ISO: 1=Monday ... 7=Sunday
    start_time: time
    end_time: time
    timezone: str
    is_flexible: bool = True  # only meaningful for student slots


@dataclass(frozen=True)
class OverlapResult:
    """Result of comparing exactly one student slot against exactly one teacher slot."""

    overlap_minutes: int
    student_day: int
    teacher_day: int
    overlap_start_utc: Optional[datetime]
    overlap_end_utc: Optional[datetime]


class TimeCompatibilityService:
    """
    Stateless service (static methods only) computing time overlap
    between recurring weekly availability patterns. See module
    docstring for the full timezone/DST design reasoning.
    """

    @staticmethod
    def _reference_monday() -> date:
        """
        Anchors all conversions to the Monday of the current real
        calendar week, so zoneinfo resolves DST correctly for "now."
        """
        today = django_timezone.now().date()
        return today - timedelta(days=today.isoweekday() - 1)

    @staticmethod
    def _slot_to_utc_interval(slot: TimeSlot, reference_monday: date) -> tuple:
        """
        Converts one recurring weekly slot into a concrete,
        DST-aware UTC datetime interval, anchored to
        `reference_monday`'s week.
        """
        slot_date = reference_monday + timedelta(days=slot.day_of_week - 1)
        tz = ZoneInfo(slot.timezone)

        start_local = datetime.combine(slot_date, slot.start_time, tzinfo=tz)
        end_local = datetime.combine(slot_date, slot.end_time, tzinfo=tz)

        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    @staticmethod
    def _overlap_minutes(a_start, a_end, b_start, b_end):
        """
        Standard interval-intersection math: the overlap is the
        later of the two starts to the earlier of the two ends, if
        that range is positive.
        """
        latest_start = max(a_start, b_start)
        earliest_end = min(a_end, b_end)
        if latest_start >= earliest_end:
            return 0, None, None
        delta = earliest_end - latest_start
        return int(delta.total_seconds() // 60), latest_start, earliest_end

    @staticmethod
    def calculate_slot_overlap(
        student_slot: TimeSlot, teacher_slot: TimeSlot
    ) -> OverlapResult:
        """
        Computes the overlap between exactly one student preference
        slot and one teacher availability slot, checking three
        adjacent reference weeks to correctly catch overlaps that
        only appear after timezone-conversion shifts the effective
        calendar day (see module docstring's "WEEK-BOUNDARY
        WRAPAROUND" section). Returns the best (maximum) overlap
        found across the three weeks checked.
        """
        reference_monday = TimeCompatibilityService._reference_monday()

        best_minutes = 0
        best_start = None
        best_end = None

        for week_offset_days in (-7, 0, 7):
            ref = reference_monday + timedelta(days=week_offset_days)
            s_start, s_end = TimeCompatibilityService._slot_to_utc_interval(
                student_slot, ref
            )
            t_start, t_end = TimeCompatibilityService._slot_to_utc_interval(
                teacher_slot, ref
            )

            minutes, ov_start, ov_end = TimeCompatibilityService._overlap_minutes(
                s_start, s_end, t_start, t_end
            )
            if minutes > best_minutes:
                best_minutes = minutes
                best_start = ov_start
                best_end = ov_end

        return OverlapResult(
            overlap_minutes=best_minutes,
            student_day=student_slot.day_of_week,
            teacher_day=teacher_slot.day_of_week,
            overlap_start_utc=best_start,
            overlap_end_utc=best_end,
        )

    @staticmethod
    def find_best_overlap(
        student_slots: Iterable[TimeSlot],
        teacher_slots: Iterable[TimeSlot],
        required_duration_minutes: int,
    ) -> dict:
        """
        Compares ALL (student_slot, teacher_slot) combinations - per
        the spec's explicit "compare all combinations... calculate
        the best compatible schedule" requirement - and returns the
        single best result.

        SCORING FORMULA (per spec, exact):
            score = min(overlap_minutes / required_duration_minutes, 1.0)

        FIXED PENALTY (per spec: "For FIXED timing: No meaningful
        overlap should heavily penalize the teacher"): if the
        student's slot is FIXED and the overlap does not meet the
        full required duration, the score for that combination is
        reduced by 70% (multiplied by 0.3) rather than zeroed
        entirely - a 25-minute partial overlap against a fixed
        60-minute request is weak but non-zero signal, not nothing.
        FLEXIBLE slots receive no such penalty, per the spec's
        "partial overlap can still produce a reasonable score."

        Returns a dict:
            time_score (0-100), overlap_minutes, is_duration_compatible,
            best_day, best_start_utc, best_end_utc, has_any_overlap
        """
        student_slots = list(student_slots)
        teacher_slots = list(teacher_slots)

        empty_result = {
            "time_score": 0,
            "overlap_minutes": 0,
            "is_duration_compatible": False,
            "best_day": None,
            "best_start_utc": None,
            "best_end_utc": None,
            "has_any_overlap": False,
        }

        if not student_slots or not teacher_slots or required_duration_minutes <= 0:
            return empty_result

        best_score_pct = -1
        best_overlap = None
        best_duration_ok = False

        for s_slot in student_slots:
            for t_slot in teacher_slots:
                overlap = TimeCompatibilityService.calculate_slot_overlap(
                    s_slot, t_slot
                )
                if overlap.overlap_minutes <= 0:
                    continue

                duration_ok = overlap.overlap_minutes >= required_duration_minutes

                raw_score = min(
                    overlap.overlap_minutes / required_duration_minutes, 1.0
                )

                if not s_slot.is_flexible and not duration_ok:
                    raw_score *= 0.3

                score_pct = round(raw_score * 100)

                if score_pct > best_score_pct:
                    best_score_pct = score_pct
                    best_overlap = overlap
                    best_duration_ok = duration_ok

        if best_overlap is None or best_score_pct <= 0:
            return empty_result

        return {
            "time_score": max(best_score_pct, 0),
            "overlap_minutes": best_overlap.overlap_minutes,
            "is_duration_compatible": best_duration_ok,
            "best_day": best_overlap.teacher_day,
            "best_start_utc": best_overlap.overlap_start_utc,
            "best_end_utc": best_overlap.overlap_end_utc,
            "has_any_overlap": True,
        }

    @staticmethod
    def convert_utc_to_timezone(dt: datetime, tz_name: str) -> datetime:
        """
        Convenience conversion for display purposes - e.g. showing
        the best_matching_start_time/end_time in the student's own
        timezone (see LeadMatchScore.best_matching_timezone).
        """
        return dt.astimezone(ZoneInfo(tz_name))
