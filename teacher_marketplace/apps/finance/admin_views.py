"""
Finance-department admin surface: dashboard KPIs, the bank-style
transaction log, pricing-change requests, and the Learning Partner
commission summary.

    GET  /api/v1/admin/finance/dashboard/
    GET  /api/v1/admin/finance/transactions/
    GET  /api/v1/admin/finance/pricing-requests/
    POST /api/v1/admin/finance/pricing-requests/
    POST /api/v1/admin/finance/pricing-requests/{id}/decide/   (Super Admin only)
    GET  /api/v1/admin/finance/learning-partners/
    GET  /api/v1/admin/finance/learning-partners/{id}/

Scoped to the Finance department for role=admin (see
apps.accounts.api_permissions.DEPARTMENT_ROUTE_SCOPE); Super Admin
reaches every route via the central short-circuit regardless. The
pricing-request decide route is left unregistered for role=admin
entirely (Super-Admin-only, same pattern as several other routes
documented in api_permissions.py).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.commissions.models import Commission, CommissionStatus, PayoutRequest, PayoutStatus
from apps.core.exceptions.custom_exceptions import ResourceNotFoundException
from apps.core.responses import APIResponse
from apps.finance.models import PricingChangeRequest, PricingChangeStatus
from apps.finance.serializers import (
    PricingChangeDecisionSerializer,
    PricingChangeRequestCreateSerializer,
    PricingChangeRequestSerializer,
)
from apps.finance.services import PricingChangeService
from apps.ops.models import AuditCategory
from apps.ops.services import AuditService
from apps.payments.models import Payment, PaymentStatus


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _week_start(now):
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _month_bounds(now):
    start = _month_start(now)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@extend_schema(tags=["Finance"], summary="Finance dashboard KPIs")
class FinanceDashboardView(APIView):
    def get(self, request):
        now = timezone.now()
        week_start = _week_start(now)
        month_start, month_end = _month_bounds(now)

        def _payment_totals(since):
            agg = Payment.objects.filter(
                status=PaymentStatus.SUCCESS, created_at__gte=since
            ).aggregate(count=Count("id"), total=Sum("amount"))
            return {
                "count": agg["count"] or 0,
                "total": str(agg["total"] or Decimal("0.00")),
            }

        def _payout_totals(since):
            agg = PayoutRequest.objects.filter(
                status=PayoutStatus.PAID, paid_at__gte=since
            ).aggregate(count=Count("id"), total=Sum("amount"))
            return {
                "count": agg["count"] or 0,
                "total": str(agg["total"] or Decimal("0.00")),
            }

        partner_totals = (
            Commission.objects.filter(
                status=CommissionStatus.ACTIVE, created_at__gte=month_start
            )
            .values("learning_partner_id", "learning_partner__first_name", "learning_partner__email")
            .annotate(total=Sum("partner_share"))
            .order_by("-total")[:10]
        )

        recent_payments = (
            Payment.objects.filter(status=PaymentStatus.SUCCESS)
            .select_related("teacher", "teacher__user")
            .order_by("-created_at")[:15]
        )

        return APIResponse.success(
            data={
                "incoming_this_week": _payment_totals(week_start),
                "incoming_this_month": _payment_totals(month_start),
                "outgoing_this_week": _payout_totals(week_start),
                "outgoing_this_month": _payout_totals(month_start),
                "top_learning_partners_this_month": [
                    {
                        "learning_partner_id": str(row["learning_partner_id"]),
                        "learning_partner_name": row["learning_partner__first_name"],
                        "learning_partner_email": row["learning_partner__email"],
                        "total": str(row["total"] or Decimal("0.00")),
                    }
                    for row in partner_totals
                    if row["learning_partner_id"] is not None
                ],
                "recent_incoming_payments": [
                    {
                        "id": str(p.id),
                        "amount": str(p.amount),
                        "teacher_name": p.teacher.user.get_full_name(),
                        "transaction_id": p.razorpay_payment_id or p.razorpay_order_id,
                        "payment_method": p.payment_method,
                        "instrument_hint": p.instrument_hint,
                        "created_at": p.created_at,
                    }
                    for p in recent_payments
                ],
            }
        )


@extend_schema(tags=["Finance"], summary="Bank-style incoming/outgoing transaction log")
class FinanceTransactionLogView(APIView):
    def get(self, request):
        params = request.query_params
        direction = params.get("direction")
        amount = params.get("amount")
        transaction_id = params.get("transaction_id", "").strip()
        account_number = params.get("account_number", "").strip()
        ifsc_code = params.get("ifsc_code", "").strip()
        date_from = parse_date(params.get("date_from", "") or "")
        date_to = parse_date(params.get("date_to", "") or "")

        rows = []

        if direction in (None, "", "incoming"):
            qs = Payment.objects.filter(status=PaymentStatus.SUCCESS).select_related(
                "teacher", "teacher__user"
            )
            if amount:
                qs = qs.filter(amount=amount)
            if transaction_id:
                qs = qs.filter(
                    Q(razorpay_payment_id__icontains=transaction_id)
                    | Q(razorpay_order_id__icontains=transaction_id)
                )
            if date_from:
                qs = qs.filter(created_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(created_at__date__lte=date_to)
            # account_number/ifsc_code never match an incoming row - Razorpay
            # doesn't expose either for card/UPI/netbanking payments.
            if not account_number and not ifsc_code:
                for p in qs.order_by("-created_at")[:500]:
                    rows.append(
                        {
                            "direction": "incoming",
                            "amount": str(p.amount),
                            "transaction_id": p.razorpay_payment_id or p.razorpay_order_id,
                            "date": p.created_at,
                            "party": p.teacher.user.get_full_name(),
                            "payment_method": p.payment_method,
                            "instrument_hint": p.instrument_hint,
                            "account_number": None,
                            "ifsc_code": None,
                            "bank_name": None,
                        }
                    )

        if direction in (None, "", "outgoing"):
            qs = PayoutRequest.objects.filter(status=PayoutStatus.PAID).select_related(
                "learning_partner"
            )
            if amount:
                qs = qs.filter(amount=amount)
            if transaction_id:
                qs = qs.filter(payout_reference__icontains=transaction_id)
            if account_number:
                qs = qs.filter(account_number__icontains=account_number)
            if ifsc_code:
                qs = qs.filter(ifsc_code__icontains=ifsc_code)
            if date_from:
                qs = qs.filter(paid_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(paid_at__date__lte=date_to)
            for pr in qs.order_by("-paid_at")[:500]:
                rows.append(
                    {
                        "direction": "outgoing",
                        "amount": str(pr.amount),
                        "transaction_id": pr.payout_reference,
                        "date": pr.paid_at,
                        "party": pr.learning_partner.first_name,
                        "payment_method": None,
                        "instrument_hint": None,
                        "account_number": pr.account_number,
                        "ifsc_code": pr.ifsc_code,
                        "bank_name": pr.bank_name,
                    }
                )

        rows.sort(key=lambda r: r["date"] or timezone.now(), reverse=True)

        paginator = _Pagination()
        page = paginator.paginate_queryset(rows, request)
        return APIResponse.paginated(
            data=page,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )


@extend_schema(
    tags=["Finance"],
    summary="List/create pricing-change requests (Finance) or list all (Super Admin)",
)
class FinancePricingRequestListCreateView(APIView):
    def get(self, request):
        qs = PricingChangeRequest.objects.select_related(
            "requested_by", "decided_by", "token_package", "subscription_plan", "lead_unlock_pricing"
        ).order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return APIResponse.success(
            data=PricingChangeRequestSerializer(qs[:200], many=True).data
        )

    def post(self, request):
        serializer = PricingChangeRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = PricingChangeService.request_change(
            request.user,
            target_type=serializer.validated_data["target_type"],
            target_id=serializer.validated_data["target_id"],
            requested_value=serializer.validated_data["requested_value"],
            note=serializer.validated_data.get("note", ""),
        )
        AuditService.record(
            request=request,
            category=AuditCategory.OPS,
            action="pricing_change_request.created",
            target=req,
            message=f"{request.user.email} requested a {req.target_type} price change "
            f"({req.current_value} -> {req.requested_value})",
        )
        return APIResponse.success(
            data=PricingChangeRequestSerializer(req).data,
            message="Pricing change requested.",
        )


@extend_schema(
    tags=["Finance"],
    summary="Approve or reject a pending pricing-change request (Super Admin)",
    request=PricingChangeDecisionSerializer,
    responses=PricingChangeRequestSerializer,
)
class SuperAdminPricingRequestDecideView(APIView):
    def post(self, request, id):
        req = PricingChangeRequest.objects.filter(id=id).first()
        if req is None:
            raise ResourceNotFoundException(detail="Pricing change request not found.")

        serializer = PricingChangeDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data["approve"]:
            req = PricingChangeService.approve(
                req, superadmin=request.user, note=serializer.validated_data.get("note", "")
            )
        else:
            req = PricingChangeService.reject(
                req, superadmin=request.user, note=serializer.validated_data.get("note", "")
            )

        AuditService.record(
            request=request,
            category=AuditCategory.OPS,
            action="pricing_change_request.approved"
            if req.status == PricingChangeStatus.APPROVED
            else "pricing_change_request.rejected",
            target=req,
            message=f"{request.user.email} {req.status} pricing change request {req.id}",
        )
        return APIResponse.success(
            data=PricingChangeRequestSerializer(req).data,
            message=f"Pricing change request {req.status}.",
        )


@extend_schema(tags=["Finance"], summary="This month's commission total per Learning Partner")
class LearningPartnerCommissionSummaryView(APIView):
    def get(self, request):
        now = timezone.now()
        month_start, month_end = _month_bounds(now)
        rows = (
            Commission.objects.filter(
                status=CommissionStatus.ACTIVE,
                learning_partner__isnull=False,
                created_at__gte=month_start,
                created_at__lt=month_end,
            )
            .values("learning_partner_id", "learning_partner__first_name", "learning_partner__email")
            .annotate(total=Sum("partner_share"), teacher_count=Count("teacher", distinct=True))
            .order_by("-total")
        )
        return APIResponse.success(
            data=[
                {
                    "learning_partner_id": str(row["learning_partner_id"]),
                    "learning_partner_name": row["learning_partner__first_name"],
                    "learning_partner_email": row["learning_partner__email"],
                    "total": str(row["total"] or Decimal("0.00")),
                    "teacher_count": row["teacher_count"],
                }
                for row in rows
            ]
        )


@extend_schema(
    tags=["Finance"], summary="This month's commission breakdown by teacher, for one Learning Partner"
)
class LearningPartnerCommissionDetailView(APIView):
    def get(self, request, learning_partner_id):
        now = timezone.now()
        month_start, month_end = _month_bounds(now)
        rows = (
            Commission.objects.filter(
                status=CommissionStatus.ACTIVE,
                learning_partner_id=learning_partner_id,
                created_at__gte=month_start,
                created_at__lt=month_end,
            )
            .select_related("teacher", "teacher__user")
            .values("teacher_id", "teacher__user__first_name", "teacher__user__last_name", "teacher__user__email")
            .annotate(total=Sum("partner_share"), count=Count("id"))
            .order_by("-total")
        )
        return APIResponse.success(
            data=[
                {
                    "teacher_id": str(row["teacher_id"]),
                    "teacher_name": f"{row['teacher__user__first_name']} {row['teacher__user__last_name']}".strip(),
                    "teacher_email": row["teacher__user__email"],
                    "total": str(row["total"] or Decimal("0.00")),
                    "purchase_count": row["count"],
                }
                for row in rows
            ]
        )
