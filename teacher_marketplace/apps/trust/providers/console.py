"""Console adapters - log instead of calling a real vendor (development)."""

from __future__ import annotations

import logging

from apps.trust.providers.base import ProviderResult, SMSProvider

logger = logging.getLogger("apps.trust.providers")


class ConsoleSMSProvider(SMSProvider):
    """
    Writes the SMS body to the log instead of sending it - the direct
    analogue of Django's console email backend. The OTP flow is fully
    exercisable in dev: read the code from the server log.
    """

    def send(self, *, to: str, body: str) -> ProviderResult:
        logger.info("[console-sms] to=%s | %s", to, body)
        return ProviderResult.success(
            detail="SMS logged to console.", reference="console"
        )
