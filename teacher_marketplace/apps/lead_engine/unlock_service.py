"""
Lead unlock service for the Teacher Marketplace Platform.

TWO MODES, selected by settings.TOKEN_SYSTEM_ENABLED.

ALLOWANCE MODE (TOKEN_SYSTEM_ENABLED=False - the current default):
every lead costs exactly one unlock. A teacher spends this period's
plan allowance first (Free 4 / Professional 10 / Elite 40, resetting
every LEAD_UNLOCK_CYCLE_DAYS), and only then their purchased top-up
balance, which never expires. When both are empty the unlock is
refused outright - there is no per-lead purchase to fall through to.

    1. Allowance left this period?
        YES -> spend one -> unlock -> LeadUnlockHistory
        NO  -> 2
    2. Purchased balance left?
        YES -> debit one -> unlock -> WalletTransaction + history
        NO  -> UnlockAllowanceExhausted

    Spending the allowance FIRST is deliberate: it is the bucket that
    expires, so burning it before the permanent one is always in the
    teacher's favour.

    Every plan, Free included, can buy and spend top-ups
    (settings.TOPUP_ELIGIBLE_PLANS). Packs sell CAPACITY, not PRIORITY - a
    Free teacher stays last in LeadDistributionService's tier cascade
    however many unlocks they hold, so paid teachers still see every lead
    first.

TOKEN MODE (TOKEN_SYSTEM_ENABLED=True - dormant, kept intact): the
original variable-cost economy, where the fallback after the free
quota is a per-tier token price funded by token packages.

TIER INFERENCE runs in TOKEN MODE ONLY. A Lead's pricing tier is
derived via fuzzy keyword matching against
StudentRequirement.student_class free text. This is a deliberately
approximate mechanism - student_class is free-text input (e.g.
"Grade 10", "JEE Aspirant", "Working Professional"), not a
structured field, so matching is keyword-based with a documented
fallback. Admins should be aware that unusual or ambiguous
student_class text (e.g. "Preparing for something") will fall
through to the SCHOOL_TUITION default tier rather than fail the
unlock outright - an unlock should never be blocked purely because
tier inference was ambiguous. In ALLOWANCE MODE none of this runs:
get_unlock_token_cost returns a flat 1.
"""

import logging

from django.conf import settings
from django.db import transaction

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.lead_engine.models import (
    Lead,
    LeadUnlockHistory,
    LeadUnlockPricing,
    PricingTier,
)
from apps.subscriptions.services import LeadQuotaService, SubscriptionService
from apps.wallet.services import InsufficientBalanceError, WalletService

logger = logging.getLogger("apps.lead_engine.unlock")


class InsufficientBalanceForUnlock(InsufficientBalanceError):
    """
    TOKEN MODE. Distinct exception (extending InsufficientBalanceError)
    so the unlock view can catch this SPECIFICALLY and respond with the
    spec's exact prompt: "Insufficient Balance. Prompt User:
    Purchase Token Package" - including package-browsing guidance
    in the error response, not just a generic wallet error.
    """

    default_detail = (
        "Insufficient token balance to unlock this lead's contact details. "
        "Please purchase a token package."
    )
    error_code = "INSUFFICIENT_BALANCE_FOR_UNLOCK"


class UnlockAllowanceExhausted(ValidationException):
    """
    ALLOWANCE MODE. The teacher has spent this period's plan allowance and
    has no spendable purchased unlocks left. A distinct error_code from
    INSUFFICIENT_BALANCE_FOR_UNLOCK because the remedy is different and the
    frontend prompts differently: upgrade the plan, buy a top-up pack, or
    wait for the reset - never "buy tokens".
    """

    default_detail = "You have used all your unlocks for this period."
    error_code = "UNLOCK_ALLOWANCE_EXHAUSTED"


# ==========================================================
# TIER INFERENCE (fuzzy keyword matching on student_class)
# ==========================================================
_COMPETITIVE_KEYWORDS = (
    "competitive",
    "jee",
    "neet",
    "upsc",
    "cat",
    "gate",
    "ssc",
    "clat",
    "cgl",
    "banking exam",
    "entrance exam",
    "exam prep",
)
_CORPORATE_KEYWORDS = (
    "corporate",
    "professional",
    "employee",
    "workplace",
    "adult learner",
)
_HIGHER_SECONDARY_KEYWORDS = (
    "11",
    "12",
    "higher secondary",
    "puc",
    "intermediate",
    "hsc",
)


def infer_pricing_tier(student_class: str) -> str:
    """
    Infers a PricingTier from free-text student_class via keyword
    matching, checked in order of specificity (most specific
    categories first, so e.g. "12th grade JEE aspirant" correctly
    matches COMPETITIVE_EXAMS rather than the more generic
    HIGHER_SECONDARY match on "12").

    Falls back to SCHOOL_TUITION (the lowest-cost tier, per the
    spec's example ordering) if no keyword matches at all - this
    is a deliberate choice to never block an unlock over ambiguous
    text; see module docstring.
    """
    if not student_class:
        return PricingTier.SCHOOL_TUITION

    text = student_class.lower()

    if any(keyword in text for keyword in _COMPETITIVE_KEYWORDS):
        return PricingTier.COMPETITIVE_EXAMS
    if any(keyword in text for keyword in _CORPORATE_KEYWORDS):
        return PricingTier.CORPORATE_TRAINING
    if any(keyword in text for keyword in _HIGHER_SECONDARY_KEYWORDS):
        return PricingTier.HIGHER_SECONDARY

    return PricingTier.SCHOOL_TUITION


def get_unlock_token_cost(lead: Lead) -> int:
    """
    Returns the cost to unlock the given lead's contact details.

    ALLOWANCE MODE pins this to settings.FIXED_LEAD_UNLOCK_COST (1) and
    returns before any tier work happens - so LeadUnlockPricing, PricingTier
    and the fuzzy student_class keyword matcher are all bypassed entirely
    rather than merely ignored. Every lead is worth exactly one unlock.

    TOKEN MODE resolves a per-tier price from the lead's inferred pricing
    tier, falling back to 10 tokens (the spec's lowest example price, School
    Tuition) if no LeadUnlockPricing row exists for that tier - i.e. if an
    admin hasn't configured pricing yet, unlocking still works rather than
    hard-failing on missing configuration.
    """
    if not settings.TOKEN_SYSTEM_ENABLED:
        return settings.FIXED_LEAD_UNLOCK_COST

    tier = infer_pricing_tier(lead.student_requirement.student_class)

    pricing = LeadUnlockPricing.objects.filter(tier=tier, is_active=True).first()
    if pricing is not None:
        return pricing.token_cost

    logger.warning(
        "No active LeadUnlockPricing configured for tier '%s' - "
        "falling back to default cost of 10 tokens.",
        tier,
    )
    return 10


# ==========================================================
# UNLOCK WORKFLOW
# ==========================================================
class UnlockResult:
    """
    Small plain-data result object returned by unlock_lead_contact,
    giving the view everything it needs to build a response without
    re-querying afterward.
    """

    def __init__(self, lead: Lead, is_free_unlock: bool, tokens_deducted: int):
        self.lead = lead
        self.is_free_unlock = is_free_unlock
        self.tokens_deducted = tokens_deducted


def unlock_lead_contact(teacher, lead: Lead) -> UnlockResult:
    """
    Executes the spec's exact Lead Unlock Logic for the given
    teacher and lead.

    The phone-reachability gate (apps.trust) runs FIRST, deliberately
    OUTSIDE the unlock transaction: an unreachable student must never
    cost the teacher a free lead or a token, and the risk-signal /
    contact-check rows it records must survive even though the unlock
    itself is aborted. The quota/wallet mutation and the
    Lead/LeadUnlockHistory writes then run in a single atomic block
    (`_unlock_lead_contact_txn`) so they commit together or not at all.

    Raises:
        ValidationException: if the lead doesn't belong to this
            teacher, or is already unlocked.
        LeadContactUnreachable: reachability gate ON and the student's
            number is not reachable - the teacher is not charged.
        UnlockAllowanceExhausted: ALLOWANCE MODE - the plan allowance for
            this period is spent and there is no spendable purchased
            balance. Carries the reset date and the way out in its detail.
        InsufficientBalanceForUnlock: TOKEN MODE - no free leads AND
            insufficient wallet balance. The view should catch this
            specifically to surface the "purchase a token package" prompt.
    """
    if lead.teacher_profile.teacher_id != teacher.id:
        raise ValidationException(detail="This lead does not belong to you.")

    if lead.contact_unlocked:
        raise ValidationException(
            detail="This lead's contact details are already unlocked."
        )

    if LeadUnlockHistory.objects.filter(teacher=teacher, lead=lead).exists():
        # Defensive: contact_unlocked and unlock history should
        # never disagree, but if they somehow did, history is the
        # more authoritative signal not to double-charge.
        raise ValidationException(detail="This lead has already been unlocked.")

    # Phone-reachability gate (apps.trust) - a no-op unless
    # TRUST_ENABLE_PHONE_REACHABILITY_CHECK is on. Runs BEFORE the
    # unlock transaction so an unreachable student never costs the
    # teacher anything and the flag/signal rows are not rolled back.
    from apps.trust.services.reachability_service import ReachabilityService

    ReachabilityService.block_if_unreachable(lead.student_requirement)

    return _unlock_lead_contact_txn(teacher, lead)


def can_spend_purchased_unlocks(teacher) -> bool:
    """
    Whether the teacher may spend their purchased (never-expiring) balance
    right now.

    Governed by settings.TOPUP_ELIGIBLE_PLANS, which currently includes every
    plan - a Free teacher can both buy and spend extra unlocks. What the Free
    plan does NOT buy is priority: LeadDistributionService offers each lead to
    Elite, then Professional, then Free, so a Free teacher's purchased unlocks
    only ever apply to the leads that reach them.

    The check is kept (rather than hard-coded True) so re-gating top-ups to
    paid plans is a settings change, not a code change. If it is ever
    re-gated, a lapsed teacher's balance is frozen, not forfeited: it stays
    on the wallet and becomes spendable again on resubscribe.

    In TOKEN MODE anyone with tokens may spend them, as before.
    """
    if settings.TOKEN_SYSTEM_ENABLED:
        return True
    plan = SubscriptionService.get_effective_plan(teacher)
    return plan.name in settings.TOPUP_ELIGIBLE_PLANS


def _mark_unlocked(teacher, lead: Lead, *, is_free_unlock: bool, cost: int):
    """Flip the lead and write its history row. Callers hold the txn."""
    lead.contact_unlocked = True
    lead.save(update_fields=["contact_unlocked"])
    LeadUnlockHistory.objects.create(
        teacher=teacher,
        lead=lead,
        is_free_unlock=is_free_unlock,
        tokens_deducted=cost,
    )


def _exhausted_error(teacher, cost: int, could_spend_balance: bool):
    """
    Builds the refusal for a teacher with nothing left to spend, worded for
    whichever mode is live and telling them the actual way out.
    """
    if settings.TOKEN_SYSTEM_ENABLED:
        return InsufficientBalanceForUnlock(
            detail=(
                f"Insufficient token balance to unlock this lead. "
                f"Required: {cost} tokens. Please purchase a token package."
            )
        )

    quota = LeadQuotaService.get_or_create_current_quota(teacher)
    resets_in = quota.days_until_reset
    when = "tomorrow" if resets_in <= 1 else f"in {resets_in} days"

    if could_spend_balance:
        remedy = "Buy extra unlocks, upgrade your plan, or wait for your next cycle."
    else:
        remedy = (
            "Upgrade to a paid plan to buy extra unlocks, "
            "or wait for your next cycle."
        )

    return UnlockAllowanceExhausted(
        detail=(
            f"You have used all {quota.total_free_leads} unlocks included in "
            f"your plan this cycle. Your allowance resets {when}. {remedy}"
        )
    )


@transaction.atomic
def _unlock_lead_contact_txn(teacher, lead: Lead) -> UnlockResult:
    """The charging half of unlock_lead_contact - see that function."""
    # ------------------------------------------------------------
    # 1. This period's plan allowance (the bucket that expires).
    # ------------------------------------------------------------
    if LeadQuotaService.has_free_leads_remaining(teacher):
        LeadQuotaService.consume_free_lead(teacher)
        _mark_unlocked(teacher, lead, is_free_unlock=True, cost=0)

        logger.info(
            "Lead %s unlocked from PLAN ALLOWANCE by teacher %s",
            lead.id,
            teacher.user.email,
        )

        return UnlockResult(lead=lead, is_free_unlock=True, tokens_deducted=0)

    # ------------------------------------------------------------
    # 2. Purchased balance (never expires; paid plans only).
    # ------------------------------------------------------------
    cost = get_unlock_token_cost(lead)
    could_spend_balance = can_spend_purchased_unlocks(teacher)

    if not could_spend_balance or not WalletService.has_sufficient_balance(
        teacher, cost
    ):
        raise _exhausted_error(teacher, cost, could_spend_balance)

    WalletService.debit(
        teacher=teacher,
        amount=cost,
        description=f"Lead unlock - {lead.student_requirement.subject.name}",
        reference_id=str(lead.id),
    )
    _mark_unlocked(teacher, lead, is_free_unlock=False, cost=cost)

    logger.info(
        "Lead %s unlocked from PURCHASED balance (%d) by teacher %s",
        lead.id,
        cost,
        teacher.user.email,
    )

    return UnlockResult(lead=lead, is_free_unlock=False, tokens_deducted=cost)
