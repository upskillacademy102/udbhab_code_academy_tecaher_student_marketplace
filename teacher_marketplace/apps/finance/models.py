"""
Models for the finance app.

PricingChangeRequest replaces Finance's former direct write access to
TokenPackage.price / SubscriptionPlan.monthly_price /
LeadUnlockPricing.token_cost (apps.accounts.api_permissions -
DEPARTMENT_ROUTE_SCOPE no longer grants Finance those write methods).
Finance requests a new value; Super Admin approves (applying it to the
target row) or rejects. Mirrors apps.trust.models.
LearningPartnerTaxonomyRequest's request/review shape (pending/approved/
rejected, reviewed_by/reviewed_at) and apps.payments.models.Payment's
"exactly one of N nullable FKs" constraint pattern.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class PricingTargetType(models.TextChoices):
    TOKEN_PACKAGE = "token_package", _("Token Package")
    SUBSCRIPTION_PLAN = "subscription_plan", _("Subscription Plan")
    LEAD_UNLOCK_PRICING = "lead_unlock_pricing", _("Lead Unlock Pricing")


class PricingChangeStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")


class PricingChangeRequest(BaseModel):
    """
    A Finance admin's request to change one price field on a commercial
    catalog row. `current_value` is a snapshot taken at request time (for
    display - "was X, requesting Y" - and so a stale request is obviously
    stale if the row has since changed). Approving writes
    `requested_value` onto the target's `field_name` and marks the
    request APPROVED; rejecting leaves the target untouched.
    """

    target_type = models.CharField(
        _("target type"), max_length=20, choices=PricingTargetType.choices
    )
    token_package = models.ForeignKey(
        "payments.TokenPackage",
        related_name="pricing_requests",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    subscription_plan = models.ForeignKey(
        "subscriptions.SubscriptionPlan",
        related_name="pricing_requests",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    lead_unlock_pricing = models.ForeignKey(
        "lead_engine.LeadUnlockPricing",
        related_name="pricing_requests",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    field_name = models.CharField(
        _("field name"),
        max_length=30,
        help_text=_("Which field this request changes - 'price', 'monthly_price', or 'token_cost'."),
    )
    current_value = models.DecimalField(
        _("current value"),
        max_digits=12,
        decimal_places=2,
        help_text=_("Snapshot of the target's value at request time."),
    )
    requested_value = models.DecimalField(
        _("requested value"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=PricingChangeStatus.choices,
        default=PricingChangeStatus.PENDING,
        db_index=True,
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        related_name="pricing_change_requests",
        on_delete=models.CASCADE,
    )
    note = models.CharField(_("note"), max_length=500, blank=True)
    decided_by = models.ForeignKey(
        "accounts.User",
        related_name="pricing_change_decisions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The Super Admin who approved or rejected this request."),
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("Pricing Change Request")
        verbose_name_plural = _("Pricing Change Requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="pricing_change_request_exactly_one_target",
                check=(
                    models.Q(
                        token_package__isnull=False,
                        subscription_plan__isnull=True,
                        lead_unlock_pricing__isnull=True,
                    )
                    | models.Q(
                        token_package__isnull=True,
                        subscription_plan__isnull=False,
                        lead_unlock_pricing__isnull=True,
                    )
                    | models.Q(
                        token_package__isnull=True,
                        subscription_plan__isnull=True,
                        lead_unlock_pricing__isnull=False,
                    )
                ),
            ),
        ]

    def __str__(self):
        return f"PricingChangeRequest {self.target_type} {self.current_value}->{self.requested_value} ({self.status})"

    @property
    def target(self):
        return self.token_package or self.subscription_plan or self.lead_unlock_pricing
