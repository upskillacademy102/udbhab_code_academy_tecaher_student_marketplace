"""
Payment service layer for the Teacher Marketplace Platform.

Wraps the Razorpay Python SDK and implements the full payment
lifecycle described in the spec:

    Create Order -> (teacher pays on Razorpay's checkout) ->
    Verify Payment (client-side callback) OR Webhook (server-side,
    authoritative) -> on success: credit wallet + create wallet
    transaction.

Two independent confirmation paths exist (Verify Payment API and
Webhook API) because this is standard, recommended Razorpay
integration practice: the client-side verify call is fast/
immediate UX feedback, but the webhook is the authoritative source
of truth (it can't be spoofed or skipped by a client that closes
the browser mid-flow). Both paths call the SAME
_mark_payment_successful() method below, which is idempotent (safe
to call twice for the same payment) - so whichever path fires
first "wins" and the second becomes a safe no-op.
"""

import hashlib
import hmac
import logging
from decimal import Decimal

import razorpay
import razorpay.errors as razorpay_errors
import requests
from django.conf import settings
from django.db import transaction

from apps.core.exceptions.custom_exceptions import (
    ServiceUnavailableException,
    ValidationException,
)
from apps.payments.exceptions import PaymentAmountMismatch
from apps.payments.models import Payment, PaymentStatus, PaymentType, PaymentWebhook
from apps.wallet.services import WalletService

logger = logging.getLogger("apps.payments")


def _expected_amount_paise(payment: Payment) -> int:
    """The paise amount this Payment's order was created for (server truth)."""
    return int(round(payment.amount * Decimal("100")))


def _amounts_disagree(captured_paise, payment: Payment) -> bool:
    """True when a known captured amount does not equal the order amount."""
    if captured_paise is None:
        return False
    try:
        return int(captured_paise) != _expected_amount_paise(payment)
    except (TypeError, ValueError):
        # An unparseable amount from Razorpay is itself suspicious.
        return True


# Errors that mean "Razorpay itself failed us" - the teacher did nothing wrong,
# so we surface a clean 503 rather than a 500 stack trace.
_RAZORPAY_GATEWAY_ERRORS = (
    razorpay_errors.BadRequestError,
    razorpay_errors.GatewayError,
    razorpay_errors.ServerError,
    requests.exceptions.RequestException,
)

_PAYMENTS_UNAVAILABLE = (
    "Online payments are temporarily unavailable. Please try again in a few minutes."
)


def _get_razorpay_client():
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def _razorpay_is_configured() -> bool:
    """True only when real (non-placeholder) Razorpay credentials are set."""
    key_id = (settings.RAZORPAY_KEY_ID or "").strip()
    key_secret = (settings.RAZORPAY_KEY_SECRET or "").strip()
    if not key_id or not key_secret:
        return False
    placeholder_markers = ("your_key", "your-key", "changeme", "xxxx")
    lowered = f"{key_id} {key_secret}".lower()
    return not any(marker in lowered for marker in placeholder_markers)


class PaymentService:
    """
    All Razorpay interaction and payment lifecycle logic lives here,
    not in views - views only translate HTTP requests into calls
    against this service and shape the response.
    """

    @staticmethod
    def create_order(teacher, token_package=None, subscription_plan=None) -> Payment:
        """
        Creates a Razorpay order for EITHER a TokenPackage purchase
        OR a SubscriptionPlan purchase - exactly one must be given.
        """
        if bool(token_package) == bool(subscription_plan):
            raise ValidationException(
                detail="Provide exactly one of token_package or subscription_plan."
            )

        if token_package is not None:
            if not token_package.is_active:
                raise ValidationException(
                    detail="This token package is no longer available."
                )
            amount = token_package.final_price
            base_amount = token_package.discounted_price
            payment_type = PaymentType.TOKEN_PURCHASE
            token_count = token_package.token_count
            notes = {
                "teacher_id": str(teacher.id),
                "token_package_id": str(token_package.id),
                "token_package_name": token_package.name,
            }
        else:
            if subscription_plan.status != "active":
                raise ValidationException(
                    detail="This subscription plan is not currently available."
                )
            amount = subscription_plan.monthly_price
            # SubscriptionPlan has no GST field - the base IS the full price.
            base_amount = subscription_plan.monthly_price
            payment_type = PaymentType.SUBSCRIPTION
            token_count = None
            notes = {
                "teacher_id": str(teacher.id),
                "subscription_plan_id": str(subscription_plan.id),
                "subscription_plan_name": subscription_plan.name,
            }

        # New-account cooldown (Phase 7g) - caps a fresh account's single
        # purchase value. No-op unless TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN.
        from apps.payments.cooldown import NewAccountCooldownService

        NewAccountCooldownService.guard_order_amount(teacher, amount)

        if not _razorpay_is_configured():
            logger.error(
                "create_order called but Razorpay credentials are not configured "
                "(teacher=%s, amount=%s).",
                teacher.user.email,
                amount,
            )
            raise ServiceUnavailableException(detail=_PAYMENTS_UNAVAILABLE)

        client = _get_razorpay_client()
        amount_in_paise = int(amount * 100)

        try:
            razorpay_order = client.order.create(
                {
                    "amount": amount_in_paise,
                    "currency": "INR",
                    "payment_capture": 1,
                    "notes": notes,
                }
            )
        except _RAZORPAY_GATEWAY_ERRORS as exc:
            # A Razorpay outage / network failure must not 500 the teacher.
            logger.error(
                "Razorpay order creation failed for teacher %s (amount=%s): %s",
                teacher.user.email,
                amount,
                exc,
                exc_info=True,
            )
            raise ServiceUnavailableException(detail=_PAYMENTS_UNAVAILABLE)

        if not isinstance(razorpay_order, dict) or not razorpay_order.get("id"):
            logger.error(
                "Razorpay returned an unexpected order payload for teacher %s: %r",
                teacher.user.email,
                razorpay_order,
            )
            raise ServiceUnavailableException(detail=_PAYMENTS_UNAVAILABLE)

        payment = Payment.objects.create(
            teacher=teacher,
            payment_type=payment_type,
            token_package=token_package,
            subscription_plan=subscription_plan,
            razorpay_order_id=razorpay_order["id"],
            amount=amount,
            base_amount=base_amount,
            token_count=token_count,
            status=PaymentStatus.PENDING,
        )

        logger.info(
            "Razorpay order created: %s for teacher %s (type=%s, amount=%s)",
            razorpay_order["id"],
            teacher.user.email,
            payment_type,
            amount,
        )

        return payment

    @staticmethod
    def verify_payment(
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> Payment:
        """
        Verifies the signature Razorpay's checkout returns to the
        client after payment, per Razorpay's documented HMAC-SHA256
        verification scheme. On success, marks the Payment
        successful (crediting the wallet). Raises ValidationException
        if the signature is invalid or the order can't be found.
        """
        try:
            payment = Payment.objects.select_related("teacher", "token_package").get(
                razorpay_order_id=razorpay_order_id
            )
        except Payment.DoesNotExist:
            raise ValidationException(detail="Payment order not found.")

        expected_signature = hmac.new(
            key=settings.RAZORPAY_KEY_SECRET.encode(),
            msg=f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, razorpay_signature):
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "Signature verification failed."
            payment.save(update_fields=["status", "failure_reason"])
            logger.warning(
                "Payment signature verification FAILED for order %s", razorpay_order_id
            )
            from apps.payments.risk import PaymentRiskService

            PaymentRiskService.note_failed_payment(payment.teacher)
            raise ValidationException(detail="Payment verification failed.")

        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.save(update_fields=["razorpay_payment_id", "razorpay_signature"])

        # Defence in depth: the HMAC only proves the client relayed a real
        # order/payment pair - ask Razorpay directly what it captured and
        # refuse to credit if it isn't the order amount.
        captured = PaymentService._fetch_captured_amount_paise(razorpay_payment_id)
        return PaymentService._mark_payment_successful(
            payment, captured_amount_paise=captured
        )

    @staticmethod
    def process_webhook(
        payload: dict, signature: str, raw_body: bytes, event_id: str = ""
    ) -> PaymentWebhook:
        """
        Validates and processes an incoming Razorpay webhook event.
        Idempotent: if razorpay_event_id has already been recorded,
        this is a safe no-op (returns the existing PaymentWebhook
        row without reprocessing) - handles Razorpay's documented
        possibility of duplicate webhook delivery.

        ``event_id`` is the ``X-Razorpay-Event-Id`` header (Razorpay's real
        dedup key - it is NOT in the body). Falls back to a body field then
        a raw-body hash so a delivery is never dropped for lack of an id.
        """
        expected_signature = hmac.new(
            key=settings.RAZORPAY_WEBHOOK_SECRET.encode(),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            logger.warning("Webhook signature verification failed.")
            raise ValidationException(detail="Invalid webhook signature.")

        event_id = (
            (event_id or "").strip()
            or payload.get("id")
            or payload.get("event_id")
            or f"sha:{hashlib.sha256(raw_body).hexdigest()}"
        )
        event_type = payload.get("event", "unknown")

        existing = PaymentWebhook.objects.filter(razorpay_event_id=event_id).first()
        if existing is not None:
            logger.info("Duplicate webhook event ignored: %s", event_id)
            return existing

        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id")
        captured_paise = payment_entity.get("amount")
        payment = (
            Payment.objects.filter(razorpay_order_id=order_id).first()
            if order_id
            else None
        )

        webhook = PaymentWebhook.objects.create(
            payment=payment,
            event_type=event_type,
            razorpay_event_id=event_id,
            payload=payload,
        )

        try:
            if event_type == "payment.captured" and payment is not None:
                # Persist the gateway payment id if the client-side verify
                # never ran (browser closed mid-flow) - later dispute/refund
                # webhooks key off razorpay_payment_id.
                entity_pay_id = payment_entity.get("id")
                if entity_pay_id and not payment.razorpay_payment_id:
                    Payment.objects.filter(pk=payment.pk).update(
                        razorpay_payment_id=entity_pay_id
                    )
                    payment.razorpay_payment_id = entity_pay_id
                PaymentService._mark_payment_successful(
                    payment, captured_amount_paise=captured_paise
                )
                from apps.payments.risk import PaymentRiskService

                PaymentRiskService.evaluate_captured(payment, payment_entity)
            elif event_type == "payment.failed" and payment is not None:
                PaymentService._mark_payment_failed(
                    payment, reason="Payment failed (reported via webhook)."
                )
                from apps.payments.risk import PaymentRiskService

                PaymentRiskService.note_failed_payment(payment.teacher, payment_entity)
            elif event_type.startswith("payment.dispute.") or event_type in (
                "refund.created",
                "refund.processed",
            ):
                from apps.payments.disputes import DisputeService

                dispute = DisputeService.handle_webhook(event_type, payload)
                if dispute is not None and webhook.payment_id is None:
                    webhook.payment = dispute.payment
                    webhook.save(update_fields=["payment"])
            webhook.is_processed = True
            webhook.save(update_fields=["is_processed"])
        except PaymentAmountMismatch as exc:
            # The payment is already durably marked FAILED and a risk signal
            # written - record why on the webhook row but don't re-raise
            # (the endpoint still 200s so Razorpay stops retrying).
            webhook.processing_error = str(exc.detail)
            webhook.save(update_fields=["processing_error"])
            logger.warning("Webhook %s: amount mismatch, payment rejected.", event_id)
        except (
            Exception
        ) as exc:  # noqa: BLE001 - log and persist, never crash the webhook endpoint
            webhook.processing_error = str(exc)
            webhook.save(update_fields=["processing_error"])
            logger.error(
                "Error processing webhook %s: %s", event_id, exc, exc_info=True
            )

        return webhook

    @staticmethod
    def _fetch_captured_amount_paise(razorpay_payment_id: str):
        """
        Ask Razorpay what it actually captured for this payment id, in
        paise. Returns None when Razorpay is not configured (dev/tests) or
        the lookup fails - callers treat None as "cannot verify, proceed".
        """
        if not razorpay_payment_id or not _razorpay_is_configured():
            return None
        try:
            remote = _get_razorpay_client().payment.fetch(razorpay_payment_id)
        except _RAZORPAY_GATEWAY_ERRORS as exc:
            logger.warning(
                "Could not fetch Razorpay payment %s for amount verification: %s",
                razorpay_payment_id,
                exc,
            )
            return None
        if not isinstance(remote, dict):
            return None
        return remote.get("amount")

    @staticmethod
    def _reject_amount_mismatch(
        payment: Payment, captured_paise, expected_paise
    ) -> None:
        """
        A captured amount that disagrees with the order amount: refuse to
        credit, mark the Payment FAILED (committed on its own so an
        exception raised afterwards cannot roll it back), and raise a
        payment-risk signal + audit row.
        """
        Payment.objects.filter(pk=payment.pk).exclude(
            status=PaymentStatus.SUCCESS
        ).update(
            status=PaymentStatus.FAILED,
            failure_reason="Captured amount did not match the order amount.",
        )
        logger.error(
            "PAYMENT AMOUNT MISMATCH order=%s expected=%s paise, captured=%s paise",
            payment.razorpay_order_id,
            expected_paise,
            captured_paise,
        )
        try:
            from apps.ops.models import AuditCategory, AuditStatus
            from apps.ops.services import AuditService
            from apps.trust.models import RiskSignalKind
            from apps.trust.services.risk_service import RiskService

            RiskService.add_signal(
                payment.teacher.user,
                kind=RiskSignalKind.PAYMENT_RISK,
                weight=40,
                detail="Captured payment amount did not match the order amount",
                payload={
                    "payment_id": str(payment.id),
                    "order_id": payment.razorpay_order_id,
                    "expected_paise": expected_paise,
                    "captured_paise": str(captured_paise),
                },
            )
            AuditService.record(
                action="payment_amount_mismatch",
                category=AuditCategory.SECURITY,
                status=AuditStatus.FAILURE,
                actor=payment.teacher.user,
                target=payment,
                message="Captured amount did not match the order amount; payment rejected.",
                order_id=payment.razorpay_order_id,
                expected_paise=expected_paise,
                captured_paise=str(captured_paise),
            )
        except Exception:  # noqa: BLE001 - signalling must not mask the rejection
            logger.exception(
                "Failed to record amount-mismatch signal for payment %s", payment.id
            )

    @staticmethod
    def _mark_payment_successful(
        payment: Payment, *, captured_amount_paise=None
    ) -> Payment:
        """
        Confirm a payment as successful and apply its side effects.

        The server-side amount gate runs FIRST, outside the crediting
        transaction: if Razorpay captured a different amount than the
        order was created for, the payment is rejected and the wallet is
        never touched. Then `_credit_successful_payment` does the
        idempotent, row-locked credit.
        """
        if _amounts_disagree(captured_amount_paise, payment):
            PaymentService._reject_amount_mismatch(
                payment, captured_amount_paise, _expected_amount_paise(payment)
            )
            raise PaymentAmountMismatch()
        return PaymentService._credit_successful_payment(payment)

    @staticmethod
    @transaction.atomic
    def _credit_successful_payment(payment: Payment) -> Payment:
        # Re-load under a row lock so two confirmation paths (verify +
        # webhook, or two webhook retries) racing on the same payment
        # serialise here - the loser sees SUCCESS and returns a no-op
        # instead of double-crediting the wallet.
        payment = (
            Payment.objects.select_for_update(of=("self",))
            .select_related("teacher", "teacher__user", "token_package")
            .get(pk=payment.pk)
        )
        if payment.status == PaymentStatus.SUCCESS:
            return payment

        payment.status = PaymentStatus.SUCCESS
        payment.save(update_fields=["status"])

        # Learning Partner commission split (apps.commissions) - runs for
        # BOTH payment types, before the token/subscription branch below,
        # since the money has already been captured/verified for either
        # kind by this point. Idempotent - see CommissionService.credit_for_payment.
        from apps.commissions.services import CommissionService

        CommissionService.credit_for_payment(payment)

        if payment.payment_type == PaymentType.TOKEN_PURCHASE:
            from apps.notifications.services import NotificationService

            # Credit the wallet FIRST - this is the financially-critical step
            # and must not be rolled back by a downstream notification error.
            # WalletService.credit() assumes the Wallet row already exists
            # (it's created lazily on first wallet-endpoint visit); a teacher
            # can reach checkout without ever opening the wallet page, so
            # ensure it exists here.
            WalletService.get_or_create_wallet(payment.teacher)
            WalletService.credit(
                teacher=payment.teacher,
                amount=payment.token_count,
                description=f"Token package purchase - {payment.token_package.name}",
                reference_id=str(payment.id),
            )
            logger.info(
                "Payment successful: %s - credited %d tokens to %s",
                payment.razorpay_order_id,
                payment.token_count,
                payment.teacher.user.email,
            )
            # New-account cooldown (Phase 7g): freeze these tokens if the
            # account is still inside its cooldown window. No-op unless
            # TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN. Never raises.
            from apps.payments.cooldown import NewAccountCooldownService

            NewAccountCooldownService.maybe_hold_new_tokens(payment)

            # Best-effort: a notification/email failure must never fail (and
            # roll back) an otherwise-successful, already-credited payment.
            try:
                NotificationService.payment_success(payment)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "payment_success notification failed for payment %s (wallet already credited)",
                    payment.id,
                )
        else:
            logger.info(
                "Subscription payment successful: %s for %s - awaiting activation call",
                payment.razorpay_order_id,
                payment.teacher.user.email,
            )

        return payment

    @staticmethod
    def _mark_payment_failed(payment: Payment, reason: str) -> Payment:
        if payment.status in (PaymentStatus.SUCCESS, PaymentStatus.FAILED):
            return payment
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = reason
        payment.save(update_fields=["status", "failure_reason"])
        logger.info("Payment failed: %s - %s", payment.razorpay_order_id, reason)
        return payment
