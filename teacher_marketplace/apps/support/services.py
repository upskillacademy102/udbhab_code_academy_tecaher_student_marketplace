"""
SupportService - creating a ticket, Super Admin assigning it to one or more
Admins, and an assigned Admin (or Super Admin) resolving it.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.support.models import (
    ContactPreference,
    SupportTicket,
    SupportTicketAttachment,
    SupportTicketStatus,
)
from apps.trust.models import ManualReviewKind
from apps.trust.services.trust_service import TrustService

S = SupportTicketStatus


class SupportService:
    @staticmethod
    @transaction.atomic
    def create_ticket(
        reporter,
        *,
        subject: str,
        description: str,
        contact_preference: str = ContactPreference.NONE,
        files=None,
    ) -> SupportTicket:
        """Create a ticket, attach any screenshots, and open the shared
        review-queue item ops works it from. A call request bumps the
        ticket's priority in that queue (2 vs the default 3)."""
        from apps.utils.validators import validate_image_upload

        ticket = SupportTicket.objects.create(
            reporter=reporter,
            subject=(subject or "").strip()[:200],
            description=(description or "").strip()[:5000],
            contact_preference=contact_preference or ContactPreference.NONE,
        )
        for f in files or []:
            validate_image_upload(f)
            SupportTicketAttachment.objects.create(ticket=ticket, file=f)

        review = TrustService.open_review_item(
            kind=ManualReviewKind.SUPPORT_TICKET,
            summary=ticket.subject or "(no subject)",
            subject_user=reporter,
            payload={
                "ticket_id": str(ticket.id),
                "contact_preference": ticket.contact_preference,
            },
            priority=2 if ticket.contact_preference != ContactPreference.NONE else 3,
        )
        ticket.review_item = review
        ticket.save(update_fields=["review_item", "updated_at"])
        return ticket

    @staticmethod
    @transaction.atomic
    def assign(ticket: SupportTicket, admin_users, *, by) -> SupportTicket:
        ticket.assigned_admins.set(admin_users)
        if ticket.status == S.OPEN:
            ticket.status = S.ASSIGNED
            ticket.save(update_fields=["status", "updated_at"])
        return ticket

    @staticmethod
    @transaction.atomic
    def resolve(
        ticket: SupportTicket, *, by, resolution: str = "", dismiss: bool = False
    ) -> SupportTicket:
        ticket.status = S.CLOSED if dismiss else S.RESOLVED
        ticket.resolution = (resolution or "").strip()[:2000]
        ticket.resolved_by = by
        ticket.resolved_at = timezone.now()
        ticket.save(
            update_fields=[
                "status",
                "resolution",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        if ticket.review_item_id and ticket.review_item.is_open:
            TrustService.resolve_review_item(
                ticket.review_item, by=by, resolution=ticket.resolution, dismiss=dismiss
            )
        return ticket

    @staticmethod
    def can_act_on(ticket: SupportTicket, user) -> bool:
        """Whether `user` may resolve/dismiss this ticket: an assigned
        Admin, or anyone Super Admin (checked upstream by the
        is_allowed() short-circuit, so this only guards plain Admins)."""
        return ticket.assigned_admins.filter(pk=user.pk).exists()
