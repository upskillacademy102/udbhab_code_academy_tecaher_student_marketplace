"""
CaptchaService - a conditional CAPTCHA gate on the auth endpoints.

Normal users never see a challenge. Only a client that has cycled through
many distinct accounts in a short window (the classic bot-farm / account-
switching signal) is asked to solve one on its next login / register /
admin-login.

    * ``record_account_use(request, user_id)`` - call after every successful
      login or registration; adds that user to the client's rolling 24h set.
    * ``verify_or_raise(request)`` - call at the top of the auth view; a
      no-op unless ``TRUST_ENABLE_CAPTCHA`` is on AND the client is over
      ``TRUST_CAPTCHA_SWITCH_THRESHOLD`` distinct accounts, in which case a
      valid ``captcha_token`` in the request body is required.

Everything is cache-backed - no models, no migration. Cache failures fail
OPEN (never block a legitimate login because the cache hiccuped).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

from apps.trust.exceptions import CaptchaRequiredException
from apps.trust.fingerprint import client_fingerprint, client_ip
from apps.trust.providers import get_provider

logger = logging.getLogger("apps.trust.captcha")

_PREFIX = "trust:switch:"
_WINDOW_SECONDS = 24 * 60 * 60
_MAX_TRACKED = 60  # cap the stored set so the cache entry stays small


def _key(request) -> str:
    return f"{_PREFIX}{client_fingerprint(request)}"


class CaptchaService:
    @staticmethod
    def record_account_use(request, user_id) -> None:
        key = _key(request)
        try:
            seen = list(cache.get(key) or [])
            uid = str(user_id)
            if uid not in seen:
                seen.append(uid)
                seen = seen[-_MAX_TRACKED:]
            cache.set(key, seen, _WINDOW_SECONDS)  # sliding window
        except Exception:  # noqa: BLE001 - tracking must never break a login
            logger.debug("captcha switch-tracking cache write failed", exc_info=True)

    @staticmethod
    def switch_count(request) -> int:
        try:
            return len(cache.get(_key(request)) or [])
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def challenge_required(request) -> bool:
        if not getattr(settings, "TRUST_ENABLE_CAPTCHA", False):
            return False
        threshold = getattr(settings, "TRUST_CAPTCHA_SWITCH_THRESHOLD", 10)
        return CaptchaService.switch_count(request) >= threshold

    @staticmethod
    def verify_or_raise(request) -> None:
        if not CaptchaService.challenge_required(request):
            return
        token = ""
        data = getattr(request, "data", None)
        if isinstance(data, dict):
            token = str(data.get("captcha_token") or "")
        result = get_provider("captcha").verify(
            token=token, remote_ip=client_ip(request)
        )
        if not result.ok:
            logger.info(
                "captcha challenge failed for fingerprint=%s (%s)",
                client_fingerprint(request),
                result.detail,
            )
            raise CaptchaRequiredException()
