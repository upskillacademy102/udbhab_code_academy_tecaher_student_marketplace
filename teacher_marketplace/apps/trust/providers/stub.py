"""
Stub adapters - deterministic success so the happy path runs in dev and
tests, with a sentinel input to force failure when a test needs it.
"""

from __future__ import annotations

from apps.trust.providers.base import (
    CaptchaProvider,
    GeoIPProvider,
    PhoneReachabilityProvider,
    ProviderResult,
)

# A test can pass this exact value to make the stub fail deterministically.
FAIL_SENTINEL = "trust-stub-fail"


class StubPhoneReachabilityProvider(PhoneReachabilityProvider):
    def check(self, *, number: str) -> ProviderResult:
        if not number or number == FAIL_SENTINEL:
            return ProviderResult.failure("Number is not reachable.")
        return ProviderResult.success(
            detail="Number appears reachable.", reachable=True
        )


class StubCaptchaProvider(CaptchaProvider):
    def verify(self, *, token: str, remote_ip: str = "") -> ProviderResult:
        if not token or token == FAIL_SENTINEL:
            return ProviderResult.failure("CAPTCHA token missing or invalid.")
        return ProviderResult.success(detail="CAPTCHA accepted (stub).")


class StubGeoIPProvider(GeoIPProvider):
    """
    Deterministic country from the IP so tests can drive "new country"
    anomalies: 203.x.x.x -> 'SG', 8.8.x.x -> 'US', anything else -> 'IN'.
    """

    def lookup(self, *, ip: str) -> ProviderResult:
        ip = (ip or "").strip()
        if ip.startswith("203."):
            country = "SG"
        elif ip.startswith("8.8.") or ip.startswith("1.1."):
            country = "US"
        else:
            country = "IN"
        return ProviderResult.success(
            detail=f"geoip stub -> {country}", country=country
        )
