"""MSG91 adapter - real SMS delivery for OTP codes (India)."""

from __future__ import annotations

import logging
import re

import requests
from django.conf import settings

from apps.trust.providers.base import ProviderResult, SMSProvider

logger = logging.getLogger("apps.trust.providers")

MSG91_OTP_URL = "https://control.msg91.com/api/v5/otp"

_OTP_RE = re.compile(r"\b(\d{4,8})\b")


class MSG91SMSProvider(SMSProvider):
    """
    Sends the OTP through MSG91's OTP API (https://msg91.com), passing
    OUR already-generated code via `otp=` rather than letting MSG91
    generate/verify its own - ``OTPService`` stays the single source of
    truth for issuing and checking codes; MSG91 is transport only.

    Requires two settings (see ``MSG91_AUTH_KEY`` / ``MSG91_TEMPLATE_ID``
    below): an account auth key, and the ID of a DLT-approved OTP
    template created in the MSG91 dashboard - Indian telecom regulation
    requires every transactional SMS to an Indian number to render a
    pre-registered template, so the template's wording is configured on
    MSG91's side, not sent from here. ``body`` (the message OTPService
    built for the console/log adapters) is used only to pull the numeric
    code back out; it is not transmitted as free text.
    """

    def send(self, *, to: str, body: str) -> ProviderResult:
        auth_key = getattr(settings, "MSG91_AUTH_KEY", "")
        template_id = getattr(settings, "MSG91_TEMPLATE_ID", "")
        if not auth_key or not template_id:
            logger.error(
                "MSG91 SMS not sent to %s: MSG91_AUTH_KEY/MSG91_TEMPLATE_ID not configured.",
                to,
            )
            return ProviderResult.failure("SMS provider is not configured.")

        match = _OTP_RE.search(body)
        if not match:
            return ProviderResult.failure("Could not extract a code to send.")
        otp = match.group(1)

        mobile = _to_msg91_mobile(to)
        if not mobile:
            return ProviderResult.failure(f"'{to}' is not a sendable mobile number.")

        try:
            response = requests.post(
                MSG91_OTP_URL,
                params={
                    "template_id": template_id,
                    "mobile": mobile,
                    "otp": otp,
                    "authkey": auth_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("MSG91 SMS send failed for %s: %s", to, exc, exc_info=True)
            return ProviderResult.failure(
                "SMS delivery failed. Please try again shortly."
            )

        if str(data.get("type", "")).lower() != "success":
            logger.error("MSG91 SMS rejected for %s: %s", to, data)
            return ProviderResult.failure(data.get("message") or "SMS delivery failed.")

        return ProviderResult.success(
            detail="SMS sent via MSG91.", reference=str(data.get("request_id", ""))
        )


def _to_msg91_mobile(raw: str) -> str:
    """
    MSG91 expects digits only, with country code and no '+' - e.g.
    "919876543210". Accepts "+91 98765 43210", "09876543210",
    "9876543210", etc. Assumes India (91) when a bare 10-digit local
    number is given, since that's this platform's only market so far.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"91{digits[1:]}"
    return digits
