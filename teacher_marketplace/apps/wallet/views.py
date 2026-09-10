"""
Views for the wallet app.

Endpoints (wired up in apps/wallet/urls.py, next file):
    GET /api/v1/wallet/          -> MyWalletView (balance check)
    GET /api/v1/wallet/history/   -> WalletHistoryView (paginated transactions)

Both are Teacher-only per the spec's explicit permission rule:
"Students: Cannot access Wallet." There is no write endpoint in
this app at all - see serializers.py for why.
"""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import ResourceNotFoundException
from apps.core.responses import APIResponse
from apps.wallet.serializers import WalletSerializer, WalletTransactionSerializer
from apps.wallet.services import WalletService

logger = logging.getLogger("apps.wallet")


def _get_teacher_or_raise(request):
    """
    Shared helper: resolves the requesting user's Phase 1 Teacher
    record, raising a clear error if it doesn't exist yet. Mirrors
    the same pattern used in apps.teacher_profile and
    apps.lead_engine views.
    """
    teacher = getattr(request.user, "teacher_profile", None)
    if teacher is None:
        raise ResourceNotFoundException(
            detail=(
                "You must create your basic Teacher profile first "
                "(POST /api/v1/teachers/me/) before accessing your wallet."
            )
        )
    return teacher


@extend_schema(tags=["Wallet"], responses=WalletSerializer)
class MyWalletView(APIView):
    """
    GET: Returns the authenticated teacher's current wallet balance.
    Lazily creates a zero-balance wallet on first access if one
    doesn't exist yet (see WalletService.get_or_create_wallet).

    Access control is centralised: see apps.accounts.api_permissions
    (route ``wallet:my-wallet``).
    """

    @extend_schema(summary="Get my wallet balance")
    def get(self, request):
        teacher = _get_teacher_or_raise(request)
        wallet = WalletService.get_or_create_wallet(teacher)
        return APIResponse.success(data=WalletSerializer(wallet).data)


@extend_schema(tags=["Wallet"])
class WalletHistoryView(generics.ListAPIView):
    """
    GET: Paginated list of the authenticated teacher's own wallet
    transactions, newest first (per WalletTransaction.Meta.ordering).

    Access control is centralised: see apps.accounts.api_permissions
    (route ``wallet:wallet-history``).
    """

    serializer_class = WalletTransactionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            from apps.wallet.models import WalletTransaction

            return WalletTransaction.objects.none()
        teacher = _get_teacher_or_raise(self.request)
        wallet = WalletService.get_or_create_wallet(teacher)
        return wallet.transactions.all()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return APIResponse.paginated(
                data=serializer.data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)
