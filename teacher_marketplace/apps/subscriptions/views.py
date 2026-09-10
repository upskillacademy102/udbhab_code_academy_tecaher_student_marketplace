"""
Views for the subscriptions app.

Endpoints (wired up in apps/subscriptions/urls.py, next file):
    GET/POST                /api/v1/subscriptions/plans/           -> SubscriptionPlanListCreateView
    GET/PUT/PATCH/DELETE     /api/v1/subscriptions/plans/{id}/       -> SubscriptionPlanDetailView
    GET                      /api/v1/subscriptions/                  -> MySubscriptionView (current + history)
    POST                     /api/v1/subscriptions/activate/          -> ActivateSubscriptionView
    GET                      /api/v1/subscriptions/quota/             -> MyLeadQuotaView
"""

import logging

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics
from rest_framework import serializers as drf_serializers
from rest_framework.filters import SearchFilter
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.subscriptions.models import SubscriptionPlan, TeacherSubscription
from apps.subscriptions.serializers import (
    MonthlyLeadQuotaSerializer,
    SubscriptionPlanSerializer,
    SubscriptionPlanWriteSerializer,
    TeacherSubscriptionSerializer,
)
from apps.subscriptions.services import LeadQuotaService, SubscriptionService

logger = logging.getLogger("apps.subscriptions")


def _get_teacher_or_raise(request):
    teacher = getattr(request.user, "teacher_profile", None)
    if teacher is None:
        raise ResourceNotFoundException(
            detail=(
                "You must create your basic Teacher profile first "
                "(POST /api/v1/teachers/me/) before managing a subscription."
            )
        )
    return teacher


# ==========================================================
# PLANS (public read, admin write)
# ==========================================================
@extend_schema(tags=["Subscriptions"])
class SubscriptionPlanListCreateView(generics.ListCreateAPIView):
    filter_backends = [SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        qs = SubscriptionPlan.objects.all()
        # Teachers see only active plans they can subscribe to; Admin /
        # Super Admin manage every plan, inactive ones included (an inactive
        # plan is otherwise invisible in the admin UI and can't be revived).
        if getattr(self.request.user, "is_platform_staff", False):
            return qs
        return qs.filter(status="active")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SubscriptionPlanWriteSerializer
        return SubscriptionPlanSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        logger.info(
            "Subscription plan created: %s (by %s)", plan.name, request.user.email
        )
        return APIResponse.created(
            data=SubscriptionPlanSerializer(plan).data,
            message="Subscription plan created successfully.",
        )


@extend_schema(tags=["Subscriptions"])
class SubscriptionPlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = SubscriptionPlan.objects.all()
    lookup_field = "id"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return SubscriptionPlanWriteSerializer
        return SubscriptionPlanSerializer

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        logger.info(
            "Subscription plan updated: %s (by %s)", plan.name, request.user.email
        )
        return APIResponse.success(
            data=SubscriptionPlanSerializer(plan).data,
            message="Subscription plan updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        logger.info(
            "Subscription plan soft-deleted: %s (by %s)",
            instance.name,
            request.user.email,
        )
        return APIResponse.no_content(message="Subscription plan deleted successfully.")


# ==========================================================
# MY SUBSCRIPTION (current + history)
# ==========================================================
@extend_schema(tags=["Subscriptions"])
class MySubscriptionView(generics.ListAPIView):
    """
    GET: The authenticated teacher's full subscription history
    (newest first), which also shows their current subscription as
    the first item if status=active. Satisfies both "current
    subscription" and "Subscription History" from one endpoint,
    avoiding a redundant second "current" endpoint.
    """

    serializer_class = TeacherSubscriptionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TeacherSubscription.objects.none()
        teacher = _get_teacher_or_raise(self.request)
        return TeacherSubscription.objects.filter(teacher=teacher).select_related(
            "plan"
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)


# ==========================================================
# ACTIVATE / SUBSCRIBE
# ==========================================================
@extend_schema(
    tags=["Subscriptions"],
    request=inline_serializer(
        "ActivateSubscriptionRequest",
        {
            "plan_id": drf_serializers.UUIDField(),
            "payment_id": drf_serializers.UUIDField(required=False),
        },
    ),
    responses={200: TeacherSubscriptionSerializer},
)
class ActivateSubscriptionView(APIView):
    """
    POST: Activates a subscription for the authenticated teacher.

    For the Free plan (monthly_price == 0): activates immediately,
    no payment required.

    For paid plans: requires payment_id in the request body,
    referencing a Payment that is:
        - status == SUCCESS
        - payment_type == SUBSCRIPTION
        - subscription_plan == the plan being activated
        - owned by this teacher
        - not already linked to an existing TeacherSubscription
          (prevents reusing one payment to activate twice)
    """

    def post(self, request):
        from apps.payments.models import Payment, PaymentStatus, PaymentType

        teacher = _get_teacher_or_raise(request)

        plan_id = request.data.get("plan_id")
        if not plan_id:
            raise ValidationException(detail="plan_id is required.")

        try:
            plan = SubscriptionPlan.objects.get(id=plan_id, status="active")
        except SubscriptionPlan.DoesNotExist:
            raise ValidationException(detail="Subscription plan not found or inactive.")

        payment = None

        if plan.monthly_price > 0:
            payment_id = request.data.get("payment_id")
            if not payment_id:
                raise ValidationException(
                    detail="payment_id is required to activate a paid subscription plan."
                )

            try:
                payment = Payment.objects.get(id=payment_id, teacher=teacher)
            except Payment.DoesNotExist:
                raise ValidationException(detail="Payment not found.")

            if payment.status != PaymentStatus.SUCCESS:
                raise ValidationException(
                    detail="Payment has not been completed successfully."
                )
            if payment.payment_type != PaymentType.SUBSCRIPTION:
                raise ValidationException(
                    detail="This payment is not a subscription payment."
                )
            if payment.subscription_plan_id != plan.id:
                raise ValidationException(
                    detail="This payment does not match the selected plan."
                )
            if TeacherSubscription.objects.filter(payment=payment).exists():
                raise ValidationException(
                    detail="This payment has already been used to activate a subscription."
                )

        subscription = SubscriptionService.subscribe(teacher, plan, payment=payment)

        logger.info("Subscription activated: %s -> %s", request.user.email, plan.name)

        return APIResponse.created(
            data=TeacherSubscriptionSerializer(subscription).data,
            message=f"Subscribed to {plan.name} successfully.",
        )


# ==========================================================
# MY LEAD QUOTA
# ==========================================================
@extend_schema(tags=["Subscriptions"], responses=MonthlyLeadQuotaSerializer)
class MyLeadQuotaView(APIView):
    """
    GET: The authenticated teacher's current-month free lead quota
    (total, used, remaining) - a direct, standalone view of the
    data apps.lead_engine's unlock workflow checks internally.
    """

    def get(self, request):
        teacher = _get_teacher_or_raise(request)
        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        return APIResponse.success(data=MonthlyLeadQuotaSerializer(quota).data)
