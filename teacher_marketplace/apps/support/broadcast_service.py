"""
BroadcastService - sending a "circulate a message" broadcast.

Deliberately synchronous (no Celery task), matching
apps.notifications.services.NotificationService._send_email - there is no
background-worker process in the documented local-dev flow
(tools/serve-local.ps1 runs a single `manage.py runserver`), so a
worker-dependent send would silently never fire there.

Sends through the SAME provider abstractions the rest of the app already
uses (django.core.mail for email, apps.trust.providers.get_provider("sms")
for SMS) rather than a new integration - this code never special-cases
dev vs prod; whatever TRUST_SMS_PROVIDER / EMAIL_BACKEND is configured is
what runs. See apps.support.broadcast_views for the API surface.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from apps.support.models import BroadcastMessage, BroadcastRecipient
from apps.trust.providers import get_provider

logger = logging.getLogger(__name__)


class BroadcastService:
    @staticmethod
    def send(
        sent_by,
        *,
        subject: str,
        body: str,
        via_email: bool,
        via_sms: bool,
        recipients,
    ) -> BroadcastMessage:
        recipients = list(recipients)
        message = BroadcastService._create(
            sent_by,
            subject=subject,
            body=body,
            via_email=via_email,
            via_sms=via_sms,
            recipients=recipients,
        )

        for row in message.recipients.select_related("user"):
            if via_email and row.user.email:
                BroadcastService._send_email(row, message)
            if via_sms and row.user.mobile:
                BroadcastService._send_sms(row, message)
        return message

    @staticmethod
    @transaction.atomic
    def _create(sent_by, *, subject, body, via_email, via_sms, recipients) -> BroadcastMessage:
        message = BroadcastMessage.objects.create(
            sent_by=sent_by,
            subject=(subject or "").strip()[:200],
            body=(body or "").strip()[:5000],
            via_email=via_email,
            via_sms=via_sms,
            recipient_count=len(recipients),
        )
        BroadcastRecipient.objects.bulk_create(
            [BroadcastRecipient(message=message, user=u) for u in recipients]
        )
        return message

    @staticmethod
    def _send_email(row: BroadcastRecipient, message: BroadcastMessage) -> None:
        try:
            send_mail(
                subject=message.subject,
                message=message.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[row.user.email],
                fail_silently=False,
            )
            row.email_sent = True
            row.save(update_fields=["email_sent"])
        except Exception as exc:  # noqa: BLE001 - one recipient's failure must not break the batch
            row.email_error = str(exc)
            row.save(update_fields=["email_error"])
            logger.error(
                "Failed to email broadcast %s to %s: %s",
                message.id,
                row.user.email,
                exc,
                exc_info=True,
            )

    @staticmethod
    def _send_sms(row: BroadcastRecipient, message: BroadcastMessage) -> None:
        try:
            result = get_provider("sms").send(to=row.user.mobile, body=message.body)
        except Exception as exc:  # noqa: BLE001
            row.sms_error = str(exc)
            row.save(update_fields=["sms_error"])
            logger.error(
                "Failed to SMS broadcast %s to %s: %s",
                message.id,
                row.user.mobile,
                exc,
                exc_info=True,
            )
            return
        if result.ok:
            row.sms_sent = True
            row.save(update_fields=["sms_sent"])
        else:
            row.sms_error = result.detail
            row.save(update_fields=["sms_error"])
