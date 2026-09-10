"""
Coarse client fingerprinting.

Without a browser-side fingerprinting library the best we can do server-side
is hash the request's stable-ish headers plus the source IP (and an optional
client-supplied ``X-Device-Id``). This is deliberately weak - good enough to
notice "the same client cycling through many accounts", not good enough to
uniquely identify a device. Used by the conditional-CAPTCHA gate (Phase 3)
and duplicate-account detection (Phase 4).
"""

from __future__ import annotations

import hashlib


def client_ip(request) -> str:
    if request is None:
        return ""
    meta = getattr(request, "META", {})
    forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return meta.get("REMOTE_ADDR", "") or ""


def client_fingerprint(request) -> str:
    """A 32-hex-char hash of the caller's coarse client signature."""
    if request is None:
        return "unknown"
    meta = getattr(request, "META", {})
    headers = getattr(request, "headers", {})
    parts = [
        meta.get("HTTP_USER_AGENT", ""),
        meta.get("HTTP_ACCEPT", ""),
        meta.get("HTTP_ACCEPT_LANGUAGE", ""),
        meta.get("HTTP_ACCEPT_ENCODING", ""),
        headers.get("X-Device-Id", "") if hasattr(headers, "get") else "",
        client_ip(request),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
