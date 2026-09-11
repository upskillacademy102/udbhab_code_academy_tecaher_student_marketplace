"""
Serializers for the payments app.

Covers:
    - TokenPackageSerializer            -> read representation,
                                           includes computed pricing
                                           (discounted_price,
                                           gst_amount, final_price).
    - TokenPackageWriteSerializer        -> admin-only create/update.
    - PaymentSerializer                  -> read-only payment history.
    - CreateOrderInputSerializer         -> validates POST
                                           /payments/create-order/
                                           request body.
    - VerifyPaymentInputSerializer       -> validates POST
                                           /payments/verify/
                                           request body.
"""

from rest_framework import serializers

from apps.payments.models import Payment, TokenPackage


class TokenPackageSerializer(serializers.ModelSerializer):
    """
    Read representation of a TokenPackage, including the computed
    pricing breakdown a frontend needs to display "Price: X, GST: Y,
    Discount: Z%, You pay: Total" without recomputing tax math
    client-side.
    """

    discounted_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    gst_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    final_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    can_purchase = serializers.SerializerMethodField()

    def get_can_purchase(self, obj) -> bool:
        """
        Whether the requesting teacher may actually buy this pack right now.

        Driven by settings.TOPUP_ELIGIBLE_PLANS, which includes Free: EVERY
        plan may buy extra unlocks. Packs sell CAPACITY; the subscription
        sells PRIORITY. A Free teacher holding twenty top-ups still sits at
        priority_rank 0 and sees each lead only after every paid teacher in
        LeadDistributionService's cascade, so selling them capacity never
        erodes what a paid plan is actually for.

        False here means no Teacher record yet, not "wrong plan" - the
        frontend should send them to create a profile, not to upgrade.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        teacher = getattr(user, "teacher_profile", None)
        if teacher is None:
            return False
        from apps.payments.views import teacher_can_buy_topups

        return teacher_can_buy_topups(teacher)

    class Meta:
        model = TokenPackage
        fields = (
            "id",
            "name",
            "token_count",
            "price",
            "gst_percentage",
            "discount_percentage",
            "discounted_price",
            "gst_amount",
            "final_price",
            "can_purchase",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TokenPackageWriteSerializer(serializers.ModelSerializer):
    """
    Admin-only write representation for creating/updating
    TokenPackages, per the spec's "Admin should configure this"
    requirement (echoed for Token Packages generally, not just
    unlock pricing).
    """

    class Meta:
        model = TokenPackage
        fields = (
            "id",
            "name",
            "token_count",
            "price",
            "gst_percentage",
            "discount_percentage",
            "is_active",
            "sort_order",
        )
        read_only_fields = ("id",)

    def validate_name(self, value):
        return value.strip() if isinstance(value, str) else value

    def validate_token_count(self, value):
        if value <= 0:
            raise serializers.ValidationError("Token count must be positive.")
        return value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value


class PaymentSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a Payment, used for
    GET /api/v1/payments/ (history). Excludes razorpay_signature
    (internal verification artifact, not useful to display) and
    excludes teacher (implicitly the requesting user - the view
    scopes the queryset, no need to redundantly show it back).
    """

    token_package_name = serializers.CharField(
        source="token_package.name", read_only=True
    )

    class Meta:
        model = Payment
        fields = (
            "id",
            "token_package_name",
            "razorpay_order_id",
            "razorpay_payment_id",
            "amount",
            "token_count",
            "status",
            "failure_reason",
            "created_at",
        )
        read_only_fields = fields


class CreateOrderInputSerializer(serializers.Serializer):
    """
    Validates the request body for POST /api/v1/payments/create-order/.
    Exactly one of token_package_id / subscription_plan_id must be
    provided.
    """

    token_package_id = serializers.UUIDField(required=False)
    subscription_plan_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        token_package_id = attrs.get("token_package_id")
        subscription_plan_id = attrs.get("subscription_plan_id")
        if bool(token_package_id) == bool(subscription_plan_id):
            raise serializers.ValidationError(
                "Provide exactly one of token_package_id or subscription_plan_id."
            )
        return attrs


class VerifyPaymentInputSerializer(serializers.Serializer):
    """
    Validates the request body for POST /api/v1/payments/verify/,
    matching the three fields Razorpay's checkout callback provides
    to the frontend after a payment attempt completes.
    """

    razorpay_order_id = serializers.CharField(required=True)
    razorpay_payment_id = serializers.CharField(required=True)
    razorpay_signature = serializers.CharField(required=True)
