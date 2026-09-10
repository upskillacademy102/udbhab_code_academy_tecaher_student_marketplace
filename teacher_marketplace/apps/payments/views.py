"""
Views for the payments app.

Endpoints (wired up in apps/payments/urls.py, next file):
    GET/POST                /api/v1/token-packages/              -> TokenPackageListCreateView
    GET/PUT/PATCH/DELETE     /api/v1/token-packages/{id}/          -> TokenPackageDetailView
    GET                      /api/v1/payments/                     -> PaymentHistoryView
    POST                     /api/v1/payments/create-order/         -> CreateOrderView
    POST                     /api/v1/payments/verify/               -> VerifyPaymentView
    POST                     /api/v1/payments/webhook/              -> RazorpayWebhookView

Design note: RazorpayWebhookView is the ONLY endpoint in this
entire project that is deliberately exempt from CSRF protection and
does not use DRF's standard authentication - it's called by
Razorpay's servers directly, authenticated instead via HMAC
signature verification (see PaymentService.process_webhook).
"""

import json
import logging

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, permissions, status
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.payments.models import Payment, TokenPackage
from apps.payments.serializers import (
    CreateOrderInputSerializer,
    PaymentSerializer,
    TokenPackageSerializer,
    TokenPackageWriteSerializer,
    VerifyPaymentInputSerializer,
)
from apps.payments.services import PaymentService
from apps.trust.gates import (
    NotFlaggedAsDuplicate,
    NotRiskSuspended,
    RequireVerifiedEmail,
    RequireVerifiedMobile,
    default_permissions_with,
)

logger = logging.getLogger("apps.payments")


def _get_teacher_or_raise(request):
    teacher = getattr(request.user, "teacher_profile", None)
    if teacher is None:
        raise ResourceNotFoundException(
            detail=(
                "You must create your basic Teacher profile first "
                "(POST /api/v1/teachers/me/) before making a payment."
            )
        )
    return teacher


class TopUpRequiresPaidPlan(ValidationException):
    """
    A Free-plan teacher tried to buy an extra-unlock pack. Its own
    error_code so the frontend can swap the buy button for an upgrade
    prompt rather than showing a generic validation error.
    """

    default_detail = (
        "Extra unlocks are available on paid plans only. "
        "Upgrade to Professional or Elite to buy them."
    )
    error_code = "TOPUP_REQUIRES_PAID_PLAN"


def teacher_can_buy_topups(teacher) -> bool:
    """
    Whether this teacher is allowed to buy extra-unlock packs.

    Governed by settings.TOPUP_ELIGIBLE_PLANS, which currently includes every
    plan: a Free teacher may buy extra unlocks. Packs sell CAPACITY, the
    subscription sells PRIORITY - buying unlocks never moves a teacher up
    LeadDistributionService's tier cascade, so paid teachers still see every
    lead first no matter how many unlocks a Free teacher holds.

    The setting is kept as a list rather than deleted so the fence can be put
    back (["Professional", "Elite"]) without a code change if a la carte
    buying turns out to suppress paid signups.

    In TOKEN MODE anyone may buy a token package, as before.
    """
    if settings.TOKEN_SYSTEM_ENABLED:
        return True
    from apps.subscriptions.services import SubscriptionService

    plan = SubscriptionService.get_effective_plan(teacher)
    return plan.name in settings.TOPUP_ELIGIBLE_PLANS


def _require_topup_eligibility(teacher):
    if not teacher_can_buy_topups(teacher):
        raise TopUpRequiresPaidPlan()


# ==========================================================
# TOKEN PACKAGES (public read, admin write - same pattern as
# apps.subjects/apps.languages)
# ==========================================================
@extend_schema(tags=["Token Packages"])
class TokenPackageListCreateView(generics.ListCreateAPIView):
    filter_backends = [SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        qs = TokenPackage.objects.all()
        # Teachers (the buyers) only ever see purchasable packages; Admin /
        # Super Admin manage the whole catalog, deactivated rows included -
        # otherwise a package vanishes from the admin UI the moment it's
        # deactivated and can never be re-activated through it.
        if getattr(self.request.user, "is_platform_staff", False):
            return qs
        return qs.filter(is_active=True)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TokenPackageWriteSerializer
        return TokenPackageSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        package = serializer.save()
        logger.info(
            "Token package created: %s (by %s)", package.name, request.user.email
        )
        return APIResponse.created(
            data=TokenPackageSerializer(package).data,
            message="Token package created successfully.",
        )


@extend_schema(tags=["Token Packages"])
class TokenPackageDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = TokenPackage.objects.all()
    lookup_field = "id"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return TokenPackageWriteSerializer
        return TokenPackageSerializer

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        package = serializer.save()
        logger.info(
            "Token package updated: %s (by %s)", package.name, request.user.email
        )
        return APIResponse.success(
            data=TokenPackageSerializer(package).data,
            message="Token package updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        logger.info(
            "Token package soft-deleted: %s (by %s)", instance.name, request.user.email
        )
        return APIResponse.no_content(message="Token package deleted successfully.")


# ==========================================================
# PAYMENT HISTORY
# ==========================================================
@extend_schema(tags=["Payments"])
class PaymentHistoryView(generics.ListAPIView):
    """
    GET: The authenticated teacher's own payment history.
    """

    serializer_class = PaymentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        teacher = _get_teacher_or_raise(self.request)
        return Payment.objects.filter(teacher=teacher).select_related("token_package")

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


# ==========================================================
# CREATE ORDER
# ==========================================================
@extend_schema(
    tags=["Payments"],
    request=CreateOrderInputSerializer,
    responses={
        200: OpenApiResponse(
            description="`data`: Razorpay order details + our Payment id."
        )
    },
)
class CreateOrderView(APIView):
    """
    POST: Creates a Razorpay order for a TokenPackage purchase.
    Returns the Razorpay order details the frontend needs to open
    the Razorpay Checkout widget (order id, amount, currency, and
    the publishable key id).
    """

    # All four gates are no-ops while their feature flags are OFF (default).
    permission_classes = default_permissions_with(
        RequireVerifiedEmail,
        RequireVerifiedMobile,
        NotFlaggedAsDuplicate,
        NotRiskSuspended,
    )

    @extend_schema(request=CreateOrderInputSerializer)
    def post(self, request):
        teacher = _get_teacher_or_raise(request)

        input_serializer = CreateOrderInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        token_package = None
        subscription_plan = None

        if data.get("token_package_id"):
            try:
                token_package = TokenPackage.objects.get(
                    id=data["token_package_id"], is_active=True
                )
            except TokenPackage.DoesNotExist:
                raise ValidationException(detail="Token package not found or inactive.")
            _require_topup_eligibility(teacher)
        else:
            from apps.subscriptions.models import SubscriptionPlan

            try:
                subscription_plan = SubscriptionPlan.objects.get(
                    id=data["subscription_plan_id"], status="active"
                )
            except SubscriptionPlan.DoesNotExist:
                raise ValidationException(
                    detail="Subscription plan not found or inactive."
                )

        payment = PaymentService.create_order(
            teacher, token_package=token_package, subscription_plan=subscription_plan
        )

        return APIResponse.created(
            data={
                "payment_id": str(payment.id),
                "razorpay_order_id": payment.razorpay_order_id,
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                "amount": str(payment.amount),
                "currency": "INR",
                "payment_type": payment.payment_type,
            },
            message="Order created successfully. Proceed to Razorpay checkout.",
        )


# ==========================================================
# VERIFY PAYMENT
# ==========================================================
@extend_schema(
    tags=["Payments"],
    request=VerifyPaymentInputSerializer,
    responses={200: PaymentSerializer},
)
class VerifyPaymentView(APIView):
    """
    POST: Verifies a completed Razorpay payment using the
    order_id/payment_id/signature returned to the frontend by
    Razorpay's checkout callback. On success, credits the teacher's
    wallet (via PaymentService, not directly here).
    """

    @extend_schema(request=VerifyPaymentInputSerializer)
    def post(self, request):
        serializer = VerifyPaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = PaymentService.verify_payment(
            razorpay_order_id=serializer.validated_data["razorpay_order_id"],
            razorpay_payment_id=serializer.validated_data["razorpay_payment_id"],
            razorpay_signature=serializer.validated_data["razorpay_signature"],
        )

        return APIResponse.success(
            data=PaymentSerializer(payment).data,
            message="Payment verified successfully. Tokens have been credited to your wallet.",
        )


# ==========================================================
# WEBHOOK
# ==========================================================
@extend_schema(
    tags=["Payments"],
    request=None,
    auth=[],
    summary="Razorpay server-to-server webhook (HMAC-verified, no JWT)",
    responses={200: OpenApiResponse(description="Event acknowledged.")},
)
@method_decorator(csrf_exempt, name="dispatch")
class RazorpayWebhookView(APIView):
    """
    POST: Receives webhook events directly from Razorpay's servers.

    Deliberately uses AllowAny (not IsAuthenticated) - Razorpay
    cannot supply a JWT bearer token, since it isn't one of our
    users. Authentication instead happens via HMAC signature
    verification inside PaymentService.process_webhook, checked
    against the raw request body.

    csrf_exempt is required since Razorpay's server-to-server POST
    has no CSRF token and isn't a browser-originated request -
    CSRF protection is meaningless here; the HMAC signature is the
    actual security boundary for this endpoint.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature", "")
        raw_body = request.body

        try:
            payload = json.loads(raw_body)
        except (ValueError, TypeError):
            logger.warning("Received malformed webhook payload.")
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            PaymentService.process_webhook(
                payload=payload,
                signature=signature,
                raw_body=raw_body,
                # Razorpay's dedup id lives in this header, NOT the body.
                event_id=request.headers.get("X-Razorpay-Event-Id", ""),
            )
        except ValidationException:
            # Invalid signature - reject clearly, but still 400 (not
            # 500), since this is a client (Razorpay) error, not a
            # server bug.
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except Exception:  # noqa: BLE001
            # Any other failure (e.g. two concurrent deliveries racing the
            # unique event-id insert) must NOT 500 Razorpay into an endless
            # retry loop - log it and acknowledge; process_webhook is
            # idempotent so a genuine reprocess on the next delivery is safe.
            logger.exception("Unhandled error processing Razorpay webhook")

        # Razorpay expects a fast 200 OK to acknowledge receipt.
        return Response(status=status.HTTP_200_OK)
