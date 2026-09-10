"""
Regex content classifier - a real, dependency-free implementation.

Detects the off-platform-leakage patterns the platform cares about:
phone numbers, UPI VPAs, "pay me on GPay/PhonePe/Paytm" phrasing,
email addresses, and external URLs. Swappable for an ML classifier
later via ``TRUST_CONTENT_CLASSIFIER_PROVIDER``.
"""

from __future__ import annotations

import re

from apps.trust.providers.base import ContentClassifierProvider, ProviderResult

_PATTERNS = {
    # 10-15 digit runs (allowing spaces/dashes/+) that look like a phone number
    "phone_number": re.compile(r"(?<!\w)(?:\+?\d[\d\s\-]{8,14}\d)(?!\w)"),
    # UPI virtual payment address, e.g. name@okhdfcbank, 98765@upi
    "upi_vpa": re.compile(
        r"\b[\w.\-]{2,}@(?:okaxis|oksbi|okhdfcbank|okicici|ybl|paytm|upi|ibl|axl)\b",
        re.I,
    ),
    "payment_solicitation": re.compile(
        r"\b(?:g[\s\-]?pay|gpay|google\s?pay|phone[\s\-]?pe|phonepe|paytm|bhim|"
        r"pay\s?(?:me|directly|outside|cash)|upi\s?id)\b",
        re.I,
    ),
    "email_address": re.compile(r"\b[\w.\-]+@[\w\-]+\.[a-z]{2,}\b", re.I),
    "external_url": re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I),
}


class RegexContentClassifierProvider(ContentClassifierProvider):
    def classify(self, *, text: str) -> ProviderResult:
        if not text:
            return ProviderResult.success(detail="empty")

        categories = []
        matches = []
        for name, pattern in _PATTERNS.items():
            found = pattern.findall(text)
            if found:
                categories.append(name)
                matches.extend(m if isinstance(m, str) else m[0] for m in found[:5])

        if categories:
            return ProviderResult.failure(
                f"Possible off-platform contact/payment info: {', '.join(categories)}.",
                categories=categories,
                matches=matches[:10],
            )
        return ProviderResult.success(detail="clean", categories=[])
