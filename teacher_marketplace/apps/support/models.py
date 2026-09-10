"""
"Connect to Admin" - a support-ticket channel for students and teachers to
report a bug, glitch, or issue straight to a human, optionally asking for a
live video or phone call. Every ticket also opens a
``trust.ManualReviewItem`` (kind=SUPPORT_TICKET) so it shows up in the
platform's one unified "things a human must look at" queue alongside
verification evidence, user reports, disputes, etc. - see
``apps.support.services.SupportService``.

Assignment is many-to-many (``assigned_admins``), unlike
``ManualReviewItem.assignee`` (single) - the user explicitly wants a Super
Admin able to route a serious issue to more than one Admin at once.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_image_upload


class ContactPreference(models.TextChoices):
    NONE = "none", _("No call needed")
    VIDEO_CALL = "video_call", _("Request a video call")
    PHONE_CALL = "phone_call", _("Request a phone call")


class SupportTicketStatus(models.TextChoices):
    OPEN = "open", _("Open - awaiting Super Admin review")
    ASSIGNED = "assigned", _("Assigned")
    RESOLVED = "resolved", _("Resolved")
    CLOSED = "closed", _("Closed")


class SupportTicket(BaseModel):
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="support_tickets",
        on_delete=models.CASCADE,
    )
    subject = models.CharField(max_length=200)
    description = models.TextField(max_length=5000)
    contact_preference = models.CharField(
        max_length=12,
        choices=ContactPreference.choices,
        default=ContactPreference.NONE,
    )
    status = models.CharField(
        max_length=10,
        choices=SupportTicketStatus.choices,
        default=SupportTicketStatus.OPEN,
        db_index=True,
    )
    assigned_admins = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="support_tickets_assigned",
        blank=True,
    )
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="support_tickets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolution = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="support_tickets_resolved",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Support ticket")
        verbose_name_plural = _("Support tickets")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["reporter", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.subject} ({self.reporter_id})"


class SupportTicketAttachment(BaseModel):
    ticket = models.ForeignKey(
        SupportTicket, related_name="attachments", on_delete=models.CASCADE
    )
    file = models.ImageField(
        upload_to="support/attachments/%Y/%m/",
        validators=[validate_image_upload],
    )

    class Meta:
        verbose_name = _("Support ticket attachment")
        verbose_name_plural = _("Support ticket attachments")
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket"]),
        ]

    def __str__(self):
        return f"attachment for {self.ticket_id}"
