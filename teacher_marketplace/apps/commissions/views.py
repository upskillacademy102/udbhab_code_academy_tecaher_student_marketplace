"""
Learning Partner self-service commission/payout API.

    GET  /api/v1/commissions/wallet/                balance + available balance
    GET  /api/v1/commissions/wallet/transactions/    paginated ledger
    GET  /api/v1/commissions/earnings/               paginated Commission rows (own only)
    GET  /api/v1/commissions/bank-account/           current saved bank details (or 404)
    PUT  /api/v1/commissions/bank-account/           create/replace bank details
    GET  /api/v1/commissions/payouts/                own payout requests
    POST /api/v1/commissions/payouts/                request a new payout

Every view is scoped to `request.user` (a role=learning_partner User) -
a partner can never see another partner's wallet, earnings, or payouts,
same guarantee apps.learning_partner.views already gives the rest of
the LP dashboard.
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.commissions.models import Commission, LearningPartnerBankAccount, PayoutRequest
from apps.commissions.serializers import (
    CommissionEarningSerializer,
    LearningPartnerBankAccountSerializer,
    LearningPartnerWalletSerializer,
    LearningPartnerWalletTransactionSerializer,
    PayoutRequestCreateSerializer,
    PayoutRequestSerializer,
)
from apps.commissions.services import LearningPartnerWalletService, PayoutService
from apps.core.exceptions.custom_exceptions import (
    PermissionDeniedException,
    ResourceNotFoundException,
)
from apps.core.responses import APIResponse


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LearningPartnerCommissionAPIView(APIView):
    """
    Same object-level gate as apps.learning_partner.views
    .LearningPartnerAPIView - the central role-permission registry
    (apps.accounts.api_permissions) already restricts these route names
    to role=learning_partner, this is belt-and-braces defence in depth.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_learning_partner_admin:
            raise PermissionDeniedException(
                detail="This area is for Learning Partner accounts only."
            )


class MyCommissionWalletView(LearningPartnerCommissionAPIView):
    def get(self, request):
        wallet = LearningPartnerWalletService.get_or_create_wallet(request.user)
        return APIResponse.success(data=LearningPartnerWalletSerializer(wallet).data)


class MyCommissionWalletTransactionsView(LearningPartnerCommissionAPIView):
    def get(self, request):
        wallet = LearningPartnerWalletService.get_or_create_wallet(request.user)
        qs = wallet.transactions.all()
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = LearningPartnerWalletTransactionSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )


class MyEarningsView(LearningPartnerCommissionAPIView):
    def get(self, request):
        qs = Commission.objects.filter(learning_partner=request.user).select_related(
            "teacher__user"
        )
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = CommissionEarningSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )


class MyBankAccountView(LearningPartnerCommissionAPIView):
    def get(self, request):
        bank = LearningPartnerBankAccount.objects.filter(
            learning_partner=request.user
        ).first()
        if bank is None:
            raise ResourceNotFoundException(detail="No bank account saved yet.")
        return APIResponse.success(data=LearningPartnerBankAccountSerializer(bank).data)

    def put(self, request):
        bank = LearningPartnerBankAccount.objects.filter(
            learning_partner=request.user
        ).first()
        serializer = LearningPartnerBankAccountSerializer(
            instance=bank, data=request.data
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(learning_partner=request.user)
        return APIResponse.success(
            data=serializer.data, message="Bank account saved."
        )


class MyPayoutRequestsView(LearningPartnerCommissionAPIView):
    def get(self, request):
        qs = PayoutRequest.objects.filter(learning_partner=request.user)
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = PayoutRequestSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )

    def post(self, request):
        serializer = PayoutRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = PayoutService.request_payout(
            request.user, amount=serializer.validated_data["amount"]
        )
        return APIResponse.created(
            data=PayoutRequestSerializer(payout).data,
            message="Payout requested.",
        )
