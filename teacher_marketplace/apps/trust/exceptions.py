"""Trust-domain API exceptions (produce the standard error envelope)."""

from rest_framework import status

from apps.core.exceptions.custom_exceptions import BaseAPIException


class CaptchaRequiredException(BaseAPIException):
    """
    The caller must solve a CAPTCHA and resend the request with a
    ``captcha_token``. Distinct error code so the frontend can render the
    widget instead of a generic error.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Please complete the verification challenge and try again."
    default_code = "captcha_required"
    error_code = "CAPTCHA_REQUIRED"


class LeadContactUnreachable(BaseAPIException):
    """
    The student's contact number failed the reachability check, so the
    unlock was blocked BEFORE any free lead / token was spent.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This student's contact number could not be verified as reachable. "
        "You have not been charged."
    )
    default_code = "lead_contact_unreachable"
    error_code = "LEAD_CONTACT_UNREACHABLE"
