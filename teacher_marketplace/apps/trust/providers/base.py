"""
Abstract verification-provider interfaces.

Each provider does exactly one job and returns a ``ProviderResult``. The
concrete adapters that ship with the project (``console`` / ``stub`` /
``manual``) make every flow work end-to-end in development and tests
WITHOUT any third-party account:

    * ``console``  - prints/logs instead of calling out (SMS).
    * ``stub``     - returns a deterministic success (phone reachability,
                     CAPTCHA) so the happy path is exercised; a sentinel
                     input can force failure for tests.
    * ``manual``   - returns "not yet verified, needs a human" so the
                     item lands in the ManualReviewItem queue (ID,
                     liveness, penny-drop).
    * ``regex``    - a real, dependency-free implementation
                     (content classification).

Going live = write one adapter class that calls the real vendor and set
the matching ``TRUST_*_PROVIDER`` setting. Nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderResult:
    """Uniform result for every provider call."""

    ok: bool
    detail: str = ""
    reference: str = ""  # vendor reference id, or our queue-item id
    needs_manual_review: bool = False
    metadata: dict = field(default_factory=dict)

    @classmethod
    def success(
        cls, detail: str = "", reference: str = "", **metadata
    ) -> "ProviderResult":
        return cls(ok=True, detail=detail, reference=reference, metadata=metadata)

    @classmethod
    def failure(cls, detail: str, **metadata) -> "ProviderResult":
        return cls(ok=False, detail=detail, metadata=metadata)

    @classmethod
    def manual(
        cls, detail: str = "Queued for manual review.", **metadata
    ) -> "ProviderResult":
        return cls(ok=False, needs_manual_review=True, detail=detail, metadata=metadata)


class SMSProvider:
    """Send a short transactional SMS (used for OTP delivery)."""

    def send(self, *, to: str, body: str) -> ProviderResult:
        raise NotImplementedError


class IDVerificationProvider:
    """Verify a government photo ID and match the name (+ DOB if given)."""

    def verify(
        self,
        *,
        full_name: str,
        date_of_birth=None,
        document_type: str = "",
        document_ref: str = "",
    ) -> ProviderResult:
        raise NotImplementedError


class LivenessProvider:
    """Selfie liveness check, optionally face-matched against an ID photo."""

    def check(self, *, selfie_ref: str, id_photo_ref: str = "") -> ProviderResult:
        raise NotImplementedError


class PhoneReachabilityProvider:
    """Check whether a phone number is a real, currently-reachable line."""

    def check(self, *, number: str) -> ProviderResult:
        raise NotImplementedError


class PennyDropProvider:
    """Verify a bank account via a tiny credit + account-holder name match."""

    def verify(
        self, *, account_number: str, ifsc: str, expected_name: str
    ) -> ProviderResult:
        raise NotImplementedError


class CaptchaProvider:
    """Verify a solved-CAPTCHA token supplied by the client."""

    def verify(self, *, token: str, remote_ip: str = "") -> ProviderResult:
        raise NotImplementedError


class GeoIPProvider:
    """Resolve a client IP to a coarse location (country) for anomaly checks."""

    def lookup(self, *, ip: str) -> ProviderResult:
        raise NotImplementedError


class ContentClassifierProvider:
    """
    Classify a piece of free text for policy problems - primarily
    off-platform contact leakage (phone numbers, UPI IDs, "pay me on
    GPay", external links). ``metadata`` carries ``categories`` and the
    matched substrings.
    """

    def classify(self, *, text: str) -> ProviderResult:
        raise NotImplementedError
