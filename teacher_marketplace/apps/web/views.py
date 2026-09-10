"""
Frontend views. These render the app shell + page scaffold only; page
data is loaded in the browser from the DRF API (see static/js). Each
view is role-guarded so a user never sees a page they can't use — the
DRF API remains the real authorisation boundary.
"""

from django.conf import settings
from django.shortcuts import redirect, render

from apps.web.guards import (
    home_url_for,
    login_required_web,
    resolve_web_user,
    role_required,
)


# ----------------------------------------------------------------------
# Public
# ----------------------------------------------------------------------
def landing(request):
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(request, "web/landing.html")


def _safe_next(request):
    """Only echo a `next` target that stays on this site."""
    nxt = request.GET.get("next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else ""


def _portal(request):
    portal = request.GET.get("as")
    return portal if portal in ("student", "teacher") else None


def login_page(request):
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(
        request,
        "web/login.html",
        {
            "portal": _portal(request),
            "session_expired": request.GET.get("expired") == "1",
            "just_registered": request.GET.get("registered") == "1",
            "prefill_email": request.GET.get("email", ""),
            "next_url": _safe_next(request),
        },
    )


def register_page(request):
    """Public self-registration — Student or Teacher only."""
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(
        request,
        "web/register.html",
        {
            "portal": _portal(request),
            "next_url": _safe_next(request),
        },
    )


def staff_login_page(request):
    """Unlinked staff sign-in (admin approval flow + direct super-admin)."""
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(request, "web/login_staff.html", {"page_title": "Staff sign-in"})


@login_required_web
def suspended_page(request):
    """
    Shown to a risk-suspended user (the ``role_required`` guard bounces
    them here). Any signed-in user can open it; the page fetches
    ``/api/v1/appeals/suspension/`` and renders "account active" if the
    caller isn't actually restricted.
    """
    return render(
        request,
        "web/suspended.html",
        {
            "page_title": "Account under review",
            "support_email": getattr(settings, "SUPPORT_EMAIL", ""),
            "appeals_enabled": getattr(
                settings, "TRUST_ENABLE_SUSPENSION_APPEALS", False
            ),
        },
    )


# ----------------------------------------------------------------------
# Generic page factory
# ----------------------------------------------------------------------
def page(template, *, roles, title, desc="", **extra):
    @role_required(*roles)
    def view(request, **kwargs):
        ctx = {"page_title": title, "page_desc": desc}
        ctx.update(extra)
        ctx.update(kwargs)  # e.g. id from the URL
        return render(request, template, ctx)

    view.__name__ = "page_" + template.replace("/", "_").replace(".html", "")
    return view


# ----------------------------------------------------------------------
# Error handlers (wired in config/urls.py)
# ----------------------------------------------------------------------
def handler404(request, exception=None):
    user = resolve_web_user(request)
    return render(
        request,
        "web/errors/404.html",
        {"home_url": home_url_for(user) if user else "/"},
        status=404,
    )


def handler403(request, exception=None):
    user = resolve_web_user(request)
    return render(
        request,
        "web/errors/403.html",
        {"home_url": home_url_for(user) if user else "/"},
        status=403,
    )


def handler500(request):
    return render(request, "web/errors/500.html", {"home_url": "/"}, status=500)
