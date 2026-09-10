"""
ReachabilityService - is the student's phone a real, reachable line?

Runs once per requirement (result cached on ``RequirementContactCheck``).
An unreachable result blocks lead unlocks for that requirement *before*
the teacher spends a free lead or any tokens - only while
``TRUST_ENABLE_PHONE_REACHABILITY_CHECK`` is on.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.trust.exceptions import LeadContactUnreachable
from apps.trust.models import RequirementContactCheck, RiskSignalKind
from apps.trust.providers import get_provider
from apps.trust.services.risk_service import RiskService

logger = logging.getLogger("apps.trust.reachability")


class ReachabilityService:
    @staticmethod
    def enabled() -> bool:
        return bool(getattr(settings, "TRUST_ENABLE_PHONE_REACHABILITY_CHECK", False))

    @staticmethod
    def check_requirement(requirement) -> RequirementContactCheck:
        existing = RequirementContactCheck.objects.filter(
            requirement=requirement
        ).first()
        if existing is not None:
            return existing
        number = getattr(requirement.student, "mobile", "") or ""
        result = get_provider("phone_reachability").check(number=number)
        # get_or_create (not create): the same requirement's leads can be
        # unlocked by several teachers concurrently, each racing to write the
        # first check. The OneToOne makes create() a 500 on the loser;
        # get_or_create absorbs the IntegrityError and returns the winner's row.
        check, _created = RequirementContactCheck.objects.get_or_create(
            requirement=requirement,
            defaults={
                "reachable": bool(result.ok),
                "detail": (result.detail or "")[:255],
                "provider_ref": (result.reference or "")[:100],
            },
        )
        return check

    @staticmethod
    def block_if_unreachable(requirement) -> None:
        if not ReachabilityService.enabled():
            return
        check = ReachabilityService.check_requirement(requirement)
        if check.reachable:
            return
        RiskService.add_signal(
            requirement.student,
            kind=RiskSignalKind.PHONE_UNREACHABLE,
            weight=20,
            detail="Contact number failed the reachability check",
            payload={"requirement_id": str(requirement.id)},
        )
        logger.info("reachability: blocked unlock for requirement %s", requirement.id)
        raise LeadContactUnreachable()
