"""
ReconciliationService (Phase 7f) - a daily cross-check of our own payment
ledger against what actually landed.

Two ledgers must agree:
  * every SUCCESS token-purchase Payment has a matching CREDIT
    WalletTransaction (same reference_id, same token amount), and
  * no CREDIT WalletTransaction references a payment that isn't SUCCESS.

When Razorpay is configured, each SUCCESS payment is also confirmed
"captured" against the gateway. In dev/tests (placeholder keys) the remote
leg is skipped, so the internal ledger check still runs and passes on a
consistent database.

Any drift is recorded on a ``ReconciliationRun`` and raised as a
RECONCILIATION review item + SECURITY audit row.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.payments.models import Payment, PaymentStatus, PaymentType, ReconciliationRun
from apps.payments.services import _get_razorpay_client, _razorpay_is_configured
from apps.wallet.models import TransactionType, WalletTransaction

logger = logging.getLogger("apps.payments.reconciliation")


class ReconciliationService:
    @staticmethod
    def run(*, window_start=None, window_end=None) -> ReconciliationRun:
        window_end = window_end or timezone.now()
        if window_start is None:
            last = ReconciliationRun.objects.order_by("-window_end").first()
            window_start = last.window_end if last else window_end - timedelta(days=1)

        run = ReconciliationRun.objects.create(
            window_start=window_start, window_end=window_end
        )
        discrepancies: list[dict] = []

        payments = Payment.objects.filter(
            created_at__gte=window_start,
            created_at__lt=window_end,
            payment_type=PaymentType.TOKEN_PURCHASE,
        ).select_related("teacher", "token_package")

        checked = 0
        remote_ok = _razorpay_is_configured()
        client = _get_razorpay_client() if remote_ok else None

        for payment in payments:
            checked += 1
            credit = (
                WalletTransaction.objects.filter(
                    transaction_type=TransactionType.CREDIT,
                    reference_id=str(payment.id),
                )
                .order_by("created_at")
                .first()
            )

            if payment.status == PaymentStatus.SUCCESS:
                if credit is None:
                    discrepancies.append(
                        {
                            "payment_id": str(payment.id),
                            "issue": "success_payment_without_wallet_credit",
                        }
                    )
                elif payment.token_count and credit.amount != payment.token_count:
                    discrepancies.append(
                        {
                            "payment_id": str(payment.id),
                            "issue": "credit_amount_mismatch",
                            "expected": payment.token_count,
                            "credited": credit.amount,
                        }
                    )
                if remote_ok and payment.razorpay_payment_id:
                    ReconciliationService._check_remote(client, payment, discrepancies)
            else:
                if credit is not None:
                    discrepancies.append(
                        {
                            "payment_id": str(payment.id),
                            "issue": "wallet_credit_for_non_success_payment",
                            "status": payment.status,
                        }
                    )

        run.finished_at = timezone.now()
        run.payments_checked = checked
        run.discrepancies = len(discrepancies)
        run.ok = not discrepancies
        run.detail = {"discrepancies": discrepancies[:200]}
        run.save(
            update_fields=[
                "finished_at",
                "payments_checked",
                "discrepancies",
                "ok",
                "detail",
                "updated_at",
            ]
        )

        if discrepancies:
            ReconciliationService._raise_alert(run, discrepancies)
        logger.info(
            "reconciliation run: checked=%d discrepancies=%d",
            checked,
            len(discrepancies),
        )
        return run

    @staticmethod
    def _check_remote(client, payment, discrepancies) -> None:
        try:
            remote = client.payment.fetch(payment.razorpay_payment_id)
        except Exception as exc:  # noqa: BLE001 - a gateway hiccup is not drift
            logger.warning(
                "reconciliation: could not fetch %s: %s",
                payment.razorpay_payment_id,
                exc,
            )
            return
        if not isinstance(remote, dict):
            return
        if remote.get("status") not in ("captured", "authorized"):
            discrepancies.append(
                {
                    "payment_id": str(payment.id),
                    "issue": "gateway_not_captured",
                    "gateway_status": remote.get("status"),
                }
            )
        expected_paise = int(round(payment.amount * 100))
        if remote.get("amount") is not None and int(remote["amount"]) != expected_paise:
            discrepancies.append(
                {
                    "payment_id": str(payment.id),
                    "issue": "gateway_amount_mismatch",
                    "expected_paise": expected_paise,
                    "gateway_paise": remote.get("amount"),
                }
            )

    @staticmethod
    def _raise_alert(run: ReconciliationRun, discrepancies) -> None:
        try:
            from apps.ops.models import AuditCategory, AuditStatus
            from apps.ops.services import AuditService
            from apps.trust.models import ManualReviewKind
            from apps.trust.services.trust_service import TrustService

            TrustService.open_review_item(
                kind=ManualReviewKind.RECONCILIATION,
                summary=f"Payment reconciliation found {len(discrepancies)} discrepancy(ies)",
                payload={"run_id": str(run.id), "discrepancies": discrepancies[:50]},
                dedupe_key=f"recon:{run.id}",
                priority=1,
            )
            AuditService.record(
                action="payment_reconciliation_drift",
                category=AuditCategory.SECURITY,
                status=AuditStatus.FAILURE,
                message=f"{len(discrepancies)} reconciliation discrepancy(ies)",
                run_id=str(run.id),
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not raise reconciliation alert for run %s", run.id)
