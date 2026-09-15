"""
Notification service layer for the Teacher Marketplace Platform.

NotificationService.notify() is the single entry point every other
app's service layer calls to fire a notification - it creates the
Notification row AND attempts synchronous email dispatch in one
call, consistent with this project's "no task queue yet" design.

TRIGGER POINTS (where each spec event actually fires from):
    PAYMENT_SUCCESS                -> apps.payments.services.
                                       PaymentService._mark_payment_successful
    SUBSCRIPTION_ACTIVATED          -> apps.subscriptions.services.
                                       SubscriptionService.subscribe
    LEAD_UNLOCKED                   -> apps.lead_engine.unlock_service.
                                       unlock_lead_contact
    FREE_LEADS_EXHAUSTED             -> apps.lead_engine.unlock_service.
                                       unlock_lead_contact (fires when a
                                       PAID unlock happens because free
                                       quota was already at zero - i.e.
                                       the exact moment a teacher first
                                       falls through to token deduction)
    LOW_WALLET_BALANCE               -> apps.lead_engine.unlock_service.
                                       unlock_lead_contact (fires after a
                                       paid unlock if the resulting
                                       balance is at or below a configured
                                       threshold)
    SUBSCRIPTION_EXPIRY_REMINDER      -> NOT triggered by any user action -
                                       this event is inherently time-based
                                       ("your subscription expires in N
                                       days"), which requires a scheduled
                                       job (cron/Celery beat) to check
                                       expiring subscriptions daily. No
                                       task scheduler exists in this
                                       project yet (consistent with every
                                       prior "no async infra" boundary
                                       stated since Phase 2). The event
                                       type and full notification-sending
                                       logic are implemented and ready
                                       (see send_subscription_expiry_reminders
                                       below) - only the SCHEDULING
                                       mechanism to call it periodically
                                       is out of scope for Phase 3. This
                                       is flagged as a genuine gap, not
                                       silently omitted.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.notifications.models import Notification, NotificationEvent

logger = logging.getLogger("apps.notifications")

LOW_BALANCE_THRESHOLD = 20  # tokens; below this, LOW_WALLET_BALANCE fires
SUBSCRIPTION_EXPIRY_REMINDER_DAYS = 3  # remind N days before expiry


class NotificationService:

    @staticmethod
    def notify(
        user,
        event: str,
        title: str,
        message: str,
        reference_id: str = None,
        send_email: bool = True,
    ) -> Notification:
        """
        Creates a Notification row and, if send_email=True,
        attempts synchronous email dispatch via Django's configured
        EMAIL_BACKEND. Email failures are caught and logged - they
        NEVER raise back to the caller, since a notification/email
        failure must never break the underlying business operation
        (e.g. a payment should still succeed even if the
        confirmation email fails to send).
        """
        notification = Notification.objects.create(
            user=user,
            event=event,
            title=title,
            message=message,
            reference_id=reference_id,
        )

        if send_email and user.email:
            NotificationService._send_email(notification)

        return notification

    @staticmethod
    def _send_email(notification: Notification) -> None:
        try:
            send_mail(
                subject=notification.title,
                message=notification.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notification.user.email],
                fail_silently=False,
            )
            notification.is_email_sent = True
            notification.save(update_fields=["is_email_sent"])
        except (
            Exception
        ) as exc:  # noqa: BLE001 - never let email failure break the caller
            notification.email_error = str(exc)
            notification.save(update_fields=["email_error"])
            logger.error(
                "Failed to send notification email to %s for event %s: %s",
                notification.user.email,
                notification.event,
                exc,
                exc_info=True,
            )

    # ------------------------------------------------------------
    # Convenience wrappers - one per event type, so calling code in
    # other apps' services reads clearly (e.g.
    # NotificationService.payment_success(...)) rather than
    # constructing raw event/title/message strings inline at every
    # call site.
    # ------------------------------------------------------------

    @staticmethod
    def payment_success(payment):
        return NotificationService.notify(
            user=payment.teacher.user,
            event=NotificationEvent.PAYMENT_SUCCESS,
            title="Payment Successful",
            message=(
                f"Your payment of ₹{payment.amount} was successful. "
                f"{'Tokens have been credited to your wallet.' if payment.token_count else 'Your subscription is being activated.'}"
            ),
            reference_id=str(payment.id),
        )

    @staticmethod
    def subscription_activated(subscription):
        return NotificationService.notify(
            user=subscription.teacher.user,
            event=NotificationEvent.SUBSCRIPTION_ACTIVATED,
            title="Subscription Activated",
            message=(
                f"Your {subscription.plan.name} subscription is now active, "
                f"valid until {subscription.end_date.strftime('%d %b %Y')}."
            ),
            reference_id=str(subscription.id),
        )

    @staticmethod
    def lead_unlocked(unlock_history):
        return NotificationService.notify(
            user=unlock_history.teacher.user,
            event=NotificationEvent.LEAD_UNLOCKED,
            title="Lead Unlocked",
            message=(
                f"You unlocked contact details for a lead in "
                f"{unlock_history.lead.student_requirement.subject.name}."
            ),
            reference_id=str(unlock_history.lead.id),
        )

    @staticmethod
    def student_lead_unlocked(lead):
        """
        Student-facing: fires the moment a teacher unlocks THIS student's
        requirement. The student never sees who unlocked it beforehand, so
        this is their first signal that a teacher now has their contact
        details and may reach out.
        """
        requirement = lead.student_requirement
        teacher_name = lead.teacher_profile.teacher.user.get_full_name() or "A teacher"
        subject_name = requirement.subject.name
        return NotificationService.notify(
            user=requirement.student,
            event=NotificationEvent.STUDENT_LEAD_UNLOCKED,
            title="A Teacher Unlocked Your Enquiry",
            message=(
                f"{teacher_name} unlocked your {subject_name} requirement and now "
                f"has your contact details. They'll reach out to you very soon."
            ),
            reference_id=str(lead.id),
        )

    @staticmethod
    def lead_review_pending(lead):
        """
        Teacher-facing nudge: they unlocked this lead's contact details but
        haven't rated it yet. Fired at most once per lead - see
        apps.lead_engine.views.PendingRatingsView, the sole caller, which
        dedupes by checking for an existing Notification with this event and
        this lead's id before calling this.
        """
        subject_name = lead.student_requirement.subject.name
        return NotificationService.notify(
            user=lead.teacher_profile.teacher.user,
            event=NotificationEvent.LEAD_REVIEW_PENDING,
            title="Please Review Your Unlocked Lead",
            message=(
                f"You unlocked contact details for a {subject_name} enquiry but "
                f"haven't told us whether it was genuine yet. Every teacher is "
                f"asked to rate the leads they unlock - it's the only way we "
                f"catch fake ones."
            ),
            reference_id=str(lead.id),
        )

    @staticmethod
    def free_leads_exhausted(teacher):
        """
        The teacher has spent this cycle's plan allowance. Names the reset
        date rather than a token top-up, since under the allowance model
        waiting is a legitimate (and free) way out - the alternatives are
        an upgrade or a top-up pack, not "buy tokens".
        """
        from django.conf import settings

        from apps.subscriptions.services import LeadQuotaService

        if settings.TOKEN_SYSTEM_ENABLED:
            message = (
                "You've used all your free leads for this month. "
                "Further lead unlocks will use tokens from your wallet."
            )
        else:
            quota = LeadQuotaService.get_or_create_current_quota(teacher)
            resets_in = quota.days_until_reset
            when = "tomorrow" if resets_in <= 1 else f"in {resets_in} days"
            message = (
                f"You've used all {quota.total_free_leads} unlocks included in "
                f"your plan this cycle. Your allowance resets {when}. "
                f"Upgrade your plan or buy extra unlocks to keep going now."
            )

        return NotificationService.notify(
            user=teacher.user,
            event=NotificationEvent.FREE_LEADS_EXHAUSTED,
            title="Plan Unlocks Used Up",
            message=message,
        )

    @staticmethod
    def low_wallet_balance(teacher, current_balance: int):
        """
        Kept under its original event name so historical notifications still
        resolve, but reworded for whichever mode is live: "extra unlocks" is
        the teacher-facing name for the purchased balance, and the word
        "token" never reaches the screen while the token system is off.
        """
        from django.conf import settings

        if settings.TOKEN_SYSTEM_ENABLED:
            title = "Low Wallet Balance"
            message = (
                f"Your wallet balance is low ({current_balance} tokens remaining). "
                f"Consider purchasing a token package to keep unlocking leads."
            )
        else:
            title = "Extra Unlocks Running Low"
            message = (
                f"You have {current_balance} extra unlock"
                f"{'' if current_balance == 1 else 's'} left. "
                f"Buy a top-up pack to keep unlocking once your plan "
                f"allowance is used up."
            )

        return NotificationService.notify(
            user=teacher.user,
            event=NotificationEvent.LOW_WALLET_BALANCE,
            title=title,
            message=message,
        )

    @staticmethod
    def subscription_expiry_reminder(subscription):
        return NotificationService.notify(
            user=subscription.teacher.user,
            event=NotificationEvent.SUBSCRIPTION_EXPIRY_REMINDER,
            title="Subscription Expiring Soon",
            message=(
                f"Your {subscription.plan.name} subscription expires on "
                f"{subscription.end_date.strftime('%d %b %Y')}. Renew to keep your benefits."
            ),
            reference_id=str(subscription.id),
        )

    @staticmethod
    def send_subscription_expiry_reminders():
        """
        Sends SUBSCRIPTION_EXPIRY_REMINDER notifications for every
        active subscription expiring within
        SUBSCRIPTION_EXPIRY_REMINDER_DAYS. Fully implemented and
        ready to use, but NOT scheduled to run automatically (see
        module docstring) - would need to be invoked via a Django
        management command on a cron schedule, or a Celery beat
        task once a task queue is introduced in a later phase.
        Callable manually today via:
            python manage.py shell -c
            "from apps.notifications.services import NotificationService;
             NotificationService.send_subscription_expiry_reminders()"
        """
        from datetime import timedelta

        from apps.subscriptions.models import SubscriptionStatus, TeacherSubscription

        cutoff = timezone.now() + timedelta(days=SUBSCRIPTION_EXPIRY_REMINDER_DAYS)
        expiring_soon = TeacherSubscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            end_date__lte=cutoff,
            end_date__gt=timezone.now(),
        ).select_related("teacher", "teacher__user", "plan")

        count = 0
        for subscription in expiring_soon:
            already_notified = Notification.objects.filter(
                user=subscription.teacher.user,
                event=NotificationEvent.SUBSCRIPTION_EXPIRY_REMINDER,
                reference_id=str(subscription.id),
            ).exists()
            if not already_notified:
                NotificationService.subscription_expiry_reminder(subscription)
                count += 1

        logger.info("Sent %d subscription expiry reminder(s).", count)
        return count
