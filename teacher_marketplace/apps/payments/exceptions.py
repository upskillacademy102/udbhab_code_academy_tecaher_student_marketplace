"""Payment-domain exceptions (fold into the project's DRF envelope)."""

from rest_framework import status

from apps.core.exceptions.custom_exceptions import BaseAPIException


class PaymentAmountMismatch(BaseAPIException):
    """
    The amount Razorpay actually captured does not equal the amount the
    order was created for (server-computed package / plan price). The
    payment is rejected, the teacher's wallet is NOT credited, and a
    payment-risk signal + audit row are written.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = (
        "The captured payment amount does not match the order amount. "
        "This payment was not applied - contact support if you were charged."
    )
    default_code = "payment_amount_mismatch"
    error_code = "PAYMENT_AMOUNT_MISMATCH"


class RefundNotAllowed(BaseAPIException):
    """A refund was requested for tokens that are no longer refundable."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "These tokens are no longer eligible for a refund."
    default_code = "refund_not_allowed"
    error_code = "REFUND_NOT_ALLOWED"


class PaymentHeldForReview(BaseAPIException):
    """A new-account cooldown or risk hold is blocking this purchase."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This purchase is temporarily on hold while your account is reviewed. "
        "Please try again later."
    )
    default_code = "payment_held_for_review"
    error_code = "PAYMENT_HELD_FOR_REVIEW"
