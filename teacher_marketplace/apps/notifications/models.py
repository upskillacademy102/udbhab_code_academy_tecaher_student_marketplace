"""
Notification models for the Teacher Marketplace Platform.

Single Notification model, not two separate Email/InApp models -
each row represents one notification instance that may have been
delivered via email, shown in-app, or both (tracked via two
independent boolean flags: is_email_sent, is_read). This is
simpler than maintaining parallel EmailNotification/
InAppNotification tables for what is fundamentally the same
underlying event data, just consumed through two different
channels.

Phase 3 scope: notifications are created synchronously, inline,
at the point each triggering event occurs (see apps.notifications.
services.NotificationService, next file) - consistent with this
project's "no task queue yet" constraint established in Phase 2.
Email sending itself uses Django's configured EMAIL_BACKEND
(console backend in development, per config/settings/development.py
from Phase 1) - actual SMTP delivery infrastructure and async
dispatch are production/deployment concerns for a later phase.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class NotificationEvent(models.TextChoices):
    """
    Matches the spec's exact event list under "Notification
    Module -> Events".
    """

    PAYMENT_SUCCESS = "payment_success", _("Payment Success")
    SUBSCRIPTION_ACTIVATED = "subscription_activated", _("Subscription Activated")
    LEAD_UNLOCKED = "lead_unlocked", _("Lead Unlocked")
    FREE_LEADS_EXHAUSTED = "free_leads_exhausted", _("Free Leads Exhausted")
    LOW_WALLET_BALANCE = "low_wallet_balance", _("Low Wallet Balance")
    SUBSCRIPTION_EXPIRY_REMINDER = "subscription_expiry_reminder", _(
        "Subscription Expiry Reminder"
    )
    # Student-facing (the one event in this list NOT aimed at a teacher -
    # see the class docstring): fired the moment a teacher unlocks a
    # student's own requirement, so the student knows to expect contact.
    STUDENT_LEAD_UNLOCKED = "student_lead_unlocked", _("Teacher Unlocked Your Lead")
    # Fired once per lead, the first time PendingRatingsView sees a teacher
    # still hasn't rated a lead they unlocked - see that view and
    # NotificationService.lead_review_pending.
    LEAD_REVIEW_PENDING = "lead_review_pending", _("Lead Review Pending")
    # Teacher-facing: a student picked THIS teacher directly ("Learn with
    # this teacher") rather than going through the general matching pool.
    # Drives the gold nav-glow on the Offers tab until unlocked/rejected.
    DIRECT_OFFER_RECEIVED = "direct_offer_received", _("Direct Offer Received")
    # Student-facing: the teacher they picked directly rejected the offer.
    DIRECT_OFFER_DECLINED = "direct_offer_declined", _("Direct Offer Declined")
    # Teacher-facing: newly offered a lead via the general cascade (initial
    # distribution, offline cascade advance, or an online tier reveal) -
    # fills the previous gap where nothing notified a teacher they'd been
    # offered/cascaded a lead at all.
    LEAD_OFFERED = "lead_offered", _("Lead Offered")
    # Finance-department-admin-facing (added 2026-09-24, apps.finance): a
    # teacher's payment just succeeded. In-app only (see
    # NotificationService.finance_incoming_payment) - email would be noisy
    # at payment frequency.
    FINANCE_INCOMING_PAYMENT = "finance_incoming_payment", _("Incoming Payment")


class Notification(BaseModel):
    """
    A single notification instance for one user - usually a Teacher
    (every Phase 3 spec event is teacher-facing), but also a Student
    for STUDENT_LEAD_UNLOCKED (see NotificationEvent above).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="notifications",
        on_delete=models.CASCADE,
    )
    event = models.CharField(
        _("event"),
        max_length=40,
        choices=NotificationEvent.choices,
        db_index=True,
    )
    title = models.CharField(
        _("title"),
        max_length=255,
        help_text=_("Short notification headline, e.g. 'Payment Successful'."),
    )
    message = models.TextField(
        _("message"),
        help_text=_("Full notification body text."),
    )
    reference_id = models.CharField(
        _("reference id"),
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "Id of the related object (Payment, Lead, TeacherSubscription, "
            "etc.), for the frontend to deep-link to. Not a foreign key "
            "since the reference type varies by event - same reasoning "
            "as WalletTransaction.reference_id."
        ),
    )
    is_read = models.BooleanField(
        _("is read"),
        default=False,
        db_index=True,
        help_text=_("Whether the user has marked this in-app notification as read."),
    )
    is_email_sent = models.BooleanField(
        _("email sent"),
        default=False,
        help_text=_(
            "Whether an email was successfully dispatched for this notification."
        ),
    )
    email_error = models.TextField(
        _("email error"),
        null=True,
        blank=True,
        help_text=_("Populated if email dispatch failed, for debugging."),
    )

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "event"]),
        ]

    def __str__(self):
        return f"{self.get_event_display()} - {self.user.get_full_name()}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])
