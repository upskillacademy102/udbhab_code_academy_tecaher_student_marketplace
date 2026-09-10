"""
RequirementVelocityService - stops a student flooding the platform with
requirements teachers then pay to unlock and find dead.

  * ``guard(student)`` - raises 429 when the student is over the
    per-day / max-open caps (only while ``TRUST_ENABLE_REQUIREMENT_VELOCITY``
    is on).
  * ``note_abandonment(student)`` - if a large share of the student's
    *closed / expired* requirements never produced a single unlocked lead,
    records a ``REQUIREMENT_ABANDONMENT`` risk signal (flag-gated - a no-op
    while ``TRUST_ENABLE_REQUIREMENT_VELOCITY`` is off).
  * ``should_hold(student)`` - True when the student is shadow-limited
    (risk state limited/review/suspended): the requirement is created but
    left ``HELD`` (not distributed) for an admin to release.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import ThrottledException
from apps.trust.models import RiskSignalKind
from apps.trust.services.risk_service import RiskService

_ABANDON_MIN_HISTORY = 5
_ABANDON_PRODUCTIVE_RATIO = 0.20


def _enabled() -> bool:
    return bool(getattr(settings, "TRUST_ENABLE_REQUIREMENT_VELOCITY", False))


class RequirementVelocityService:
    @staticmethod
    def guard(student) -> None:
        if not _enabled():
            return
        from apps.student_requirement.models import (
            RequirementStatus,
            StudentRequirement,
        )

        day_ago = timezone.now() - timezone.timedelta(hours=24)
        recent = StudentRequirement.all_objects.filter(
            student=student, created_at__gte=day_ago
        ).count()
        if recent >= settings.TRUST_REQUIREMENT_MAX_PER_DAY:
            raise ThrottledException(
                detail="You've posted a lot of requirements today. Please try again tomorrow."
            )

        open_count = StudentRequirement.objects.filter(
            student=student,
            status__in=[RequirementStatus.OPEN, RequirementStatus.MATCHED],
        ).count()
        if open_count >= settings.TRUST_REQUIREMENT_MAX_OPEN:
            raise ThrottledException(
                detail="You have too many open requirements. Close some before posting more."
            )

    @staticmethod
    def note_abandonment(student) -> None:
        # Fully dormant unless the velocity feature is switched on - this runs
        # as a side effect of every requirement POST, so it must cost nothing
        # (and write nothing) while the flag is OFF.
        if not _enabled():
            return

        from apps.student_requirement.models import (
            RequirementStatus,
            StudentRequirement,
        )

        # Only *terminal* requirements (closed / expired) count - a student
        # whose freshly-posted requirements simply haven't been worked yet is
        # not an abandoner. Open-requirement hoarding is caught by guard()'s
        # max-open cap instead.
        terminal = StudentRequirement.all_objects.filter(
            student=student,
            status__in=[RequirementStatus.CLOSED, RequirementStatus.EXPIRED],
        )
        total = terminal.count()
        if total < _ABANDON_MIN_HISTORY:
            return
        productive = terminal.filter(leads__contact_unlocked=True).distinct().count()
        if productive / total >= _ABANDON_PRODUCTIVE_RATIO:
            return
        RiskService.add_signal(
            student,
            kind=RiskSignalKind.REQUIREMENT_ABANDONMENT,
            weight=25,
            detail=f"{productive}/{total} closed requirements produced a paid unlock",
            payload={"total": total, "productive": productive},
        )

    @staticmethod
    def should_hold(student) -> bool:
        if not _enabled():
            return False
        return RiskService.is_shadow_limited(student)
