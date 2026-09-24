"""
Admin/Super Admin side of the Learning Partner payout queue.

    GET  /api/v1/admin/payouts/                 list + filter by status
    GET  /api/v1/admin/payouts/{id}/             detail
    POST /api/v1/admin/payouts/{id}/decide/      approve or reject a PENDING request
    POST /api/v1/admin/payouts/{id}/mark-paid/   record a bank UTR, mark an APPROVED
                                                  request PAID (debits the wallet)

Scoped to the Finance department for role=admin (see
apps.accounts.api_permissions.DEPARTMENT_ROUTE_SCOPE); Super Admin
reaches every route via the central short-circuit regardless.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.commissions.models import PayoutRequest
from apps.commissions.serializers import (
    AdminPayoutRequestSerializer,
    PayoutDecisionSerializer,
    PayoutMarkPaidSerializer,
)
from apps.commissions.services import PayoutService
from apps.core.exceptions.custom_exceptions import ResourceNotFoundException
from apps.core.responses import APIResponse
from apps.ops.models import AuditCategory
from apps.ops.services import AuditService


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _get_payout_or_404(payout_id) -> PayoutRequest:
    payout = PayoutRequest.objects.filter(id=payout_id).first()
    if payout is None:
        raise ResourceNotFoundException(detail="Payout request not found.")
    return payout


@extend_schema(tags=["Commissions"], responses=AdminPayoutRequestSerializer(many=True))
class AdminPayoutListView(APIView):
    def get(self, request):
        qs = PayoutRequest.objects.select_related(
            "learning_partner", "decided_by"
        ).order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = AdminPayoutRequestSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )


@extend_schema(tags=["Commissions"], responses=AdminPayoutRequestSerializer)
class AdminPayoutDetailView(APIView):
    def get(self, request, id):
        payout = _get_payout_or_404(id)
        return APIResponse.success(data=AdminPayoutRequestSerializer(payout).data)


@extend_schema(
    tags=["Commissions"],
    summary="Approve or reject a pending payout request",
    request=PayoutDecisionSerializer,
    responses=AdminPayoutRequestSerializer,
)
class AdminPayoutDecideView(APIView):
    def post(self, request, id):
        payout = _get_payout_or_404(id)
        serializer = PayoutDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payout = PayoutService.decide(
            payout,
            admin=request.user,
            approve=serializer.validated_data["approve"],
            notes=serializer.validated_data.get("notes", ""),
        )

        AuditService.record(
            request=request,
            category=AuditCategory.OPS,
            action="payout_request.approved" if payout.status == "approved" else "payout_request.rejected",
            target=payout,
            message=f"{request.user.email} {payout.status} payout {payout.id} for {payout.learning_partner.email}",
            amount=str(payout.amount),
        )
        return APIResponse.success(
            data=AdminPayoutRequestSerializer(payout).data,
            message=f"Payout {payout.status}.",
        )


@extend_schema(
    tags=["Commissions"],
    summary="Mark an approved payout as paid (records the bank transfer reference)",
    request=PayoutMarkPaidSerializer,
    responses=AdminPayoutRequestSerializer,
)
class AdminPayoutMarkPaidView(APIView):
    def post(self, request, id):
        payout = _get_payout_or_404(id)
        serializer = PayoutMarkPaidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payout = PayoutService.mark_paid(
            payout,
            admin=request.user,
            payout_reference=serializer.validated_data["payout_reference"],
        )

        AuditService.record(
            request=request,
            category=AuditCategory.OPS,
            action="payout_request.paid",
            target=payout,
            message=f"{request.user.email} marked payout {payout.id} paid for {payout.learning_partner.email}",
            amount=str(payout.amount),
            payout_reference=payout.payout_reference,
        )
        return APIResponse.success(
            data=AdminPayoutRequestSerializer(payout).data, message="Payout marked paid."
        )
