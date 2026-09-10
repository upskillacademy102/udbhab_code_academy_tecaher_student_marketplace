"""
Security response-header middleware for the Teacher Marketplace Platform.

Adds two headers Django cannot set on its own:

    * Content-Security-Policy   - restricts where scripts / styles / images /
      frames / network calls may come from, so an injected ``<script src=…>``
      or a hijacked ``<base>`` / ``<form>`` cannot exfiltrate data or load
      attacker code. The angle-bracket + control-char field validators and
      template autoescape already make stored XSS very unlikely; CSP is the
      belt-and-braces second layer.
    * Permissions-Policy        - switches off browser features the app never
      uses (camera, microphone, geolocation, USB, …) so a compromised page
      cannot reach for them.

The remaining classic headers (``X-Content-Type-Options``, ``X-Frame-Options``,
``Referrer-Policy``, HSTS, ``Cross-Origin-Opener-Policy``) are produced by
Django's own ``SecurityMiddleware`` / ``XFrameOptionsMiddleware`` and are
configured in ``config/settings/base.py``.

Both header values are read once from settings at process start and cached on
the instance, so the per-response cost is a single ``dict.setdefault`` - no
computation, no I/O, no measurable latency.

Placed LAST in ``MIDDLEWARE`` so it runs on the way out for every response,
including error responses produced higher up the stack.
"""

from __future__ import annotations

from django.conf import settings

# ----------------------------------------------------------------------
# Defaults. Overridable per-environment via settings so a deployment with,
# say, a different payment provider or a CDN can adjust without a code change.
# ----------------------------------------------------------------------
# NOTE on 'unsafe-inline' / 'unsafe-eval' in script-src: the server-rendered
# frontend uses Alpine.js, which evaluates directive expressions
# (x-data / @click / x-text) via the Function constructor ('unsafe-eval')
# and ships two tiny inline <script> blocks ('unsafe-inline'). These keep the
# UI working. CSP still meaningfully blocks: loading external script files,
# framing the site, <base> hijacking, sending forms off-site, plugins/objects,
# and outbound connections to anywhere but the API + the payment gateway.
DEFAULT_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://checkout.razorpay.com https://*.razorpay.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https://*.razorpay.com; "
    "font-src 'self' data:; "
    "connect-src 'self' https://*.razorpay.com https://lumberjack.razorpay.com; "
    "frame-src 'self' https://api.razorpay.com https://*.razorpay.com; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'"
)

DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(self), "
    "publickey-credentials-get=(), screen-wake-lock=(), usb=(), "
    "xr-spatial-tracking=()"
)


class SecurityHeadersMiddleware:
    """Attach Content-Security-Policy + Permissions-Policy to every response."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._csp = getattr(
            settings, "CONTENT_SECURITY_POLICY", DEFAULT_CONTENT_SECURITY_POLICY
        )
        self._permissions_policy = getattr(
            settings, "PERMISSIONS_POLICY", DEFAULT_PERMISSIONS_POLICY
        )
        # Report-only mode lets a new/tightened policy be observed in the
        # browser console (via a report endpoint or DevTools) without actually
        # blocking anything - useful when rolling out a stricter policy.
        self._report_only = bool(
            getattr(settings, "CONTENT_SECURITY_POLICY_REPORT_ONLY", False)
        )
        self._csp_header = (
            "Content-Security-Policy-Report-Only"
            if self._report_only
            else "Content-Security-Policy"
        )

    def __call__(self, request):
        response = self.get_response(request)
        if self._csp and self._csp_header not in response:
            response[self._csp_header] = self._csp
        if self._permissions_policy and "Permissions-Policy" not in response:
            response["Permissions-Policy"] = self._permissions_policy
        return response
