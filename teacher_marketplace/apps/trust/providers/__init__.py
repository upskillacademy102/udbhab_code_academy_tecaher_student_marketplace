"""
Provider factory.

``get_provider(kind)`` returns a ready-to-use provider instance, choosing
the concrete class from ``settings.TRUST_<KIND>_PROVIDER`` (same shape as
``GEOCODING_PROVIDER``). Unknown kind or unknown provider name raises
``ImproperlyConfigured`` at call time - loud, not silent.

    kind                 setting                            dev default
    -------------------  ---------------------------------  -----------
    sms                  TRUST_SMS_PROVIDER                 console
    id                   TRUST_ID_PROVIDER                  manual
    liveness             TRUST_LIVENESS_PROVIDER            manual
    phone_reachability   TRUST_PHONE_REACHABILITY_PROVIDER  stub
    penny_drop           TRUST_PENNY_DROP_PROVIDER          manual
    captcha              TRUST_CAPTCHA_PROVIDER             stub
    content_classifier   TRUST_CONTENT_CLASSIFIER_PROVIDER  regex

sms also has a real adapter: "msg91" (apps.trust.providers.msg91.MSG91SMSProvider),
enabled by setting TRUST_SMS_PROVIDER=msg91 plus MSG91_AUTH_KEY/MSG91_TEMPLATE_ID.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.trust.providers.base import ProviderResult  # noqa: F401  (re-export)
from apps.trust.providers.console import ConsoleSMSProvider
from apps.trust.providers.manual import (
    ManualIDVerificationProvider,
    ManualLivenessProvider,
    ManualPennyDropProvider,
)
from apps.trust.providers.msg91 import MSG91SMSProvider
from apps.trust.providers.regex_classifier import RegexContentClassifierProvider
from apps.trust.providers.stub import (
    StubCaptchaProvider,
    StubGeoIPProvider,
    StubPhoneReachabilityProvider,
)

_REGISTRY = {
    "sms": {"console": ConsoleSMSProvider, "msg91": MSG91SMSProvider},
    "id": {"manual": ManualIDVerificationProvider},
    "liveness": {"manual": ManualLivenessProvider},
    "phone_reachability": {"stub": StubPhoneReachabilityProvider},
    "penny_drop": {"manual": ManualPennyDropProvider},
    "captcha": {"stub": StubCaptchaProvider},
    "content_classifier": {"regex": RegexContentClassifierProvider},
    "geoip": {"stub": StubGeoIPProvider},
}


def _setting_name(kind: str) -> str:
    return f"TRUST_{kind.upper()}_PROVIDER"


def get_provider(kind: str):
    if kind not in _REGISTRY:
        raise ImproperlyConfigured(f"Unknown trust provider kind: {kind!r}")
    name = getattr(settings, _setting_name(kind), None)
    if not name:
        raise ImproperlyConfigured(f"{_setting_name(kind)} is not set.")
    try:
        return _REGISTRY[kind][name]()
    except KeyError:
        available = ", ".join(sorted(_REGISTRY[kind]))
        raise ImproperlyConfigured(
            f"{_setting_name(kind)}={name!r} is not a known provider "
            f"for kind {kind!r}. Available: {available}."
        )
