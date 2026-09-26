"""
Service layer for Finance pricing-change requests.

Entry points other code calls:
    PricingChangeService.request_change(admin, ...)  - Finance admin, from
        FinancePricingRequestListCreateView.post
    PricingChangeService.approve(req, ...) / .reject(req, ...) - Super
        Admin, from SuperAdminPricingRequestDecideView.post
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.finance.models import (
    PricingChangeRequest,
    PricingChangeStatus,
    PricingTargetType,
)

# Which model field each target type's price lives on.
_FIELD_BY_TARGET_TYPE = {
    PricingTargetType.TOKEN_PACKAGE: "price",
    PricingTargetType.SUBSCRIPTION_PLAN: "monthly_price",
    PricingTargetType.LEAD_UNLOCK_PRICING: "token_cost",
}


def _target_model(target_type: str):
    if target_type == PricingTargetType.TOKEN_PACKAGE:
        from apps.payments.models import TokenPackage

        return TokenPackage
    if target_type == PricingTargetType.SUBSCRIPTION_PLAN:
        from apps.subscriptions.models import SubscriptionPlan

        return SubscriptionPlan
    if target_type == PricingTargetType.LEAD_UNLOCK_PRICING:
        from apps.lead_engine.models import LeadUnlockPricing

        return LeadUnlockPricing
    raise ValidationException(detail=f"Unknown pricing target type: {target_type}")


def _target_fk_field(target_type: str) -> str:
    return {
        PricingTargetType.TOKEN_PACKAGE: "token_package",
        PricingTargetType.SUBSCRIPTION_PLAN: "subscription_plan",
        PricingTargetType.LEAD_UNLOCK_PRICING: "lead_unlock_pricing",
    }[target_type]


class PricingChangeService:
    @staticmethod
    def request_change(
        admin, *, target_type: str, target_id, requested_value: Decimal, note: str = ""
    ) -> PricingChangeRequest:
        if requested_value is None or requested_value <= 0:
            raise ValidationException(detail="Requested price must be greater than zero.")

        model = _target_model(target_type)
        target = model.objects.filter(pk=target_id).first()
        if target is None:
            raise ResourceNotFoundException(detail="Pricing target not found.")

        field_name = _FIELD_BY_TARGET_TYPE[target_type]
        current_value = Decimal(getattr(target, field_name))

        return PricingChangeRequest.objects.create(
            target_type=target_type,
            field_name=field_name,
            current_value=current_value,
            requested_value=requested_value,
            requested_by=admin,
            note=(note or "")[:500],
            **{_target_fk_field(target_type): target},
        )

    @staticmethod
    @transaction.atomic
    def approve(req: PricingChangeRequest, *, superadmin, note: str = "") -> PricingChangeRequest:
        req = PricingChangeRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != PricingChangeStatus.PENDING:
            raise ValidationException(detail=f"This request is already {req.status}.")

        model = _target_model(req.target_type)
        target = model.objects.select_for_update().get(
            pk=getattr(req, _target_fk_field(req.target_type) + "_id")
        )
        value = req.requested_value
        if req.field_name == "token_cost":
            value = int(value)
        setattr(target, req.field_name, value)
        target.save(update_fields=[req.field_name, "updated_at"])

        req.status = PricingChangeStatus.APPROVED
        req.decided_by = superadmin
        req.decided_at = timezone.now()
        req.decision_note = (note or "")[:500]
        req.save(
            update_fields=[
                "status",
                "decided_by",
                "decided_at",
                "decision_note",
                "updated_at",
            ]
        )
        return req

    @staticmethod
    @transaction.atomic
    def reject(req: PricingChangeRequest, *, superadmin, note: str = "") -> PricingChangeRequest:
        req = PricingChangeRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != PricingChangeStatus.PENDING:
            raise ValidationException(detail=f"This request is already {req.status}.")

        req.status = PricingChangeStatus.REJECTED
        req.decided_by = superadmin
        req.decided_at = timezone.now()
        req.decision_note = (note or "")[:500]
        req.save(
            update_fields=[
                "status",
                "decided_by",
                "decided_at",
                "decision_note",
                "updated_at",
            ]
        )
        return req
