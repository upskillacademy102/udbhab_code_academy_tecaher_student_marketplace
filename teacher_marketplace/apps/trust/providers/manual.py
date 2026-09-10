"""
Manual adapters - no automated decision is possible without a vendor, so
the check returns "needs a human" and the caller opens a ManualReviewItem.
An admin then approves/rejects it from the review queue.
"""

from __future__ import annotations

from apps.trust.providers.base import (
    IDVerificationProvider,
    LivenessProvider,
    PennyDropProvider,
    ProviderResult,
)

_MSG = "Submitted - a reviewer will verify this shortly."


class ManualIDVerificationProvider(IDVerificationProvider):
    def verify(
        self, *, full_name, date_of_birth=None, document_type="", document_ref=""
    ) -> ProviderResult:
        return ProviderResult.manual(_MSG)


class ManualLivenessProvider(LivenessProvider):
    def check(self, *, selfie_ref, id_photo_ref="") -> ProviderResult:
        return ProviderResult.manual(_MSG)


class ManualPennyDropProvider(PennyDropProvider):
    def verify(self, *, account_number, ifsc, expected_name) -> ProviderResult:
        return ProviderResult.manual(_MSG)
