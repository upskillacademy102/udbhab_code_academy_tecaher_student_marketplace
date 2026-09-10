"""
DedupeService - spot two accounts that belong to the same real person.

We store a *normalised, hashed* signature per user for each of: phone
(digits only, last 10), email (Gmail dot/plus canonicalised), device
(client fingerprint), and later government-ID number + selfie hash
(Phase 5). When a new account's signature collides with an existing
account's, a ``DuplicateSignal`` + a ``ManualReviewItem`` are opened. If
``TRUST_ENABLE_DEDUP_BLOCKING`` is ON, the flagged account's lead / paid
actions are blocked until a reviewer resolves it.
"""

from __future__ import annotations

import hashlib
import logging
import re

from django.conf import settings

from apps.trust.models import (
    DuplicateSignal,
    IdentitySignature,
    IdentitySignatureKind,
    ManualReviewKind,
)
from apps.trust.services.trust_service import TrustService

logger = logging.getLogger("apps.trust.dedupe")

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


class DedupeService:
    # ----- normalisation ------------------------------------------------
    @staticmethod
    def normalize_phone(raw) -> str:
        digits = re.sub(r"\D", "", str(raw or "")).lstrip("0")
        return digits[-10:] if len(digits) > 10 else digits

    @staticmethod
    def normalize_email(raw) -> str:
        value = str(raw or "").strip().lower()
        if "@" not in value:
            return value
        local, _, domain = value.partition("@")
        local = local.split("+", 1)[0]
        if domain in _GMAIL_DOMAINS:
            local = local.replace(".", "")
            domain = "gmail.com"
        return f"{local}@{domain}"

    @staticmethod
    def _hash(kind: str, normalised: str) -> str:
        return hashlib.sha256(
            f"{kind}:{normalised}:{settings.SECRET_KEY}".encode()
        ).hexdigest()

    # ----- recording --------------------------------------------------
    @staticmethod
    def record_signature(
        user, *, kind: str, raw_value, source: str = ""
    ) -> tuple[IdentitySignature | None, bool]:
        if not raw_value:
            return None, False
        if kind == IdentitySignatureKind.PHONE:
            norm = DedupeService.normalize_phone(raw_value)
        elif kind == IdentitySignatureKind.EMAIL:
            norm = DedupeService.normalize_email(raw_value)
        else:
            norm = str(raw_value).strip()
        if not norm:
            return None, False

        sig, created = IdentitySignature.objects.get_or_create(
            user=user,
            kind=kind,
            value_hash=DedupeService._hash(kind, norm),
            defaults={"source": source},
        )
        return sig, created

    # ----- scanning -------------------------------------------------
    @staticmethod
    def scan(user) -> list[DuplicateSignal]:
        """
        Compare every one of ``user``'s signatures against all other users';
        record any new collision and (re)open one review item. Idempotent.
        """
        signals: list[DuplicateSignal] = []
        for sig in IdentitySignature.objects.filter(user=user):
            matches = (
                IdentitySignature.objects.filter(
                    kind=sig.kind, value_hash=sig.value_hash
                )
                .exclude(user_id=user.id)
                .exclude(user__is_deleted=True)
                .select_related("user")
            )
            for match in matches:
                ds, created = DuplicateSignal.objects.get_or_create(
                    user=user,
                    matched_user=match.user,
                    kind=sig.kind,
                    defaults={"value_hash": sig.value_hash},
                )
                if created:
                    signals.append(ds)

        if signals:
            kinds = sorted({s.kind for s in signals})
            matched_emails = sorted({s.matched_user.email for s in signals})
            item = TrustService.open_review_item(
                kind=ManualReviewKind.DUPLICATE_ACCOUNT,
                summary=(
                    f"{user.email} shares {', '.join(kinds)} with "
                    f"{len(matched_emails)} other account(s)"
                ),
                subject_user=user,
                payload={"kinds": kinds, "matched": matched_emails},
                dedupe_key=f"dupe:{user.id}",
                priority=2,
            )
            DuplicateSignal.objects.filter(id__in=[s.id for s in signals]).update(
                review_item=item
            )
            from apps.trust.models import RiskSignalKind
            from apps.trust.services.risk_service import RiskService

            RiskService.add_signal(
                user,
                kind=RiskSignalKind.DUPLICATE_ACCOUNT,
                weight=30,
                detail=f"Shares {', '.join(kinds)} with {len(matched_emails)} account(s)",
                payload={"kinds": kinds, "matched": matched_emails[:10]},
            )
            logger.info(
                "dedupe: %s flagged - shares %s with %s",
                user.email,
                kinds,
                matched_emails,
            )
        return signals

    @staticmethod
    def record_and_scan_on_register(user, *, request=None) -> list[DuplicateSignal]:
        from apps.trust.fingerprint import client_fingerprint

        DedupeService.record_signature(
            user,
            kind=IdentitySignatureKind.PHONE,
            raw_value=user.mobile,
            source="register",
        )
        DedupeService.record_signature(
            user,
            kind=IdentitySignatureKind.EMAIL,
            raw_value=user.email,
            source="register",
        )
        if request is not None:
            DedupeService.record_signature(
                user,
                kind=IdentitySignatureKind.DEVICE,
                raw_value=client_fingerprint(request),
                source="register",
            )
        return DedupeService.scan(user)

    @staticmethod
    def record_and_scan_device(user, *, request) -> list[DuplicateSignal]:
        from apps.trust.fingerprint import client_fingerprint

        _, created = DedupeService.record_signature(
            user,
            kind=IdentitySignatureKind.DEVICE,
            raw_value=client_fingerprint(request),
            source="login",
        )
        return DedupeService.scan(user) if created else []

    # ----- blocking / resolution ----------------------------------
    @staticmethod
    def is_blocked(user) -> bool:
        if not getattr(settings, "TRUST_ENABLE_DEDUP_BLOCKING", False):
            return False
        return DuplicateSignal.objects.filter(
            user_id=getattr(user, "id", None), resolved=False
        ).exists()

    @staticmethod
    def resolve_for_review_item(item) -> int:
        return DuplicateSignal.objects.filter(review_item=item, resolved=False).update(
            resolved=True
        )
