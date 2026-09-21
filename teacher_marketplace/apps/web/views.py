"""
Frontend views. These render the app shell + page scaffold only; page
data is loaded in the browser from the DRF API (see static/js). Each
view is role-guarded so a user never sees a page they can't use — the
DRF API remains the real authorisation boundary.
"""

from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect, render

from apps.web.guards import (
    ROLE_HOME,
    home_url_for,
    login_required_web,
    resolve_web_user,
    role_required,
)
from apps.web.taxonomy import public_taxonomy


# ----------------------------------------------------------------------
# Public
# ----------------------------------------------------------------------
def landing(request):
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    # Subject / language options come from the database so a Super Admin
    # adding one shows up here without a deploy. See apps/web/taxonomy.py
    # for why this is a model read and not an API call.
    return render(request, "web/landing.html", public_taxonomy())


def _safe_next(request):
    """Only echo a `next` target that stays on this site."""
    nxt = request.GET.get("next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else ""


def _portal(request):
    portal = request.GET.get("as")
    return portal if portal in ("student", "teacher") else None


def _redirect_authenticated(request, user):
    """
    Where an already-authenticated user lands when they hit /login/ or
    /register/ (with or without ?as=<portal>). If the requested portal
    differs from their current one:
      - they already have that portal's profile -> switch to it right
        away (dual-role accounts should move between portals with no
        friction once both exist).
      - they don't have it yet -> send them to the add-role
        confirmation screen instead of silently creating anything.
    No portal requested, or it matches their current role: unchanged,
    straight to their own home.
    """
    portal = _portal(request)
    if not portal or portal == user.role:
        return redirect(home_url_for(user))

    has_profile = (
        user.has_teacher_profile if portal == "teacher" else user.has_student_profile
    )
    if not has_profile:
        return redirect(f"/add-role/?as={portal}")

    from apps.accounts.role_switch import switch_active_role

    switch_active_role(user, portal)
    return redirect(ROLE_HOME[portal])


def login_page(request):
    user = resolve_web_user(request)
    if user is not None:
        return _redirect_authenticated(request, user)
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
        return _redirect_authenticated(request, user)
    return render(
        request,
        "web/register.html",
        {
            "portal": _portal(request),
            "next_url": _safe_next(request),
            **public_taxonomy(),
        },
    )


def add_role_page(request):
    """
    Confirmation screen for adding a second role (Student and/or
    Teacher) to an already-authenticated account. See
    apps.accounts.role_switch for why this never creates a new User.
    """
    user = resolve_web_user(request)
    if user is None:
        return redirect(f"/login/?next={quote(request.get_full_path())}")
    request.web_user = user

    portal = _portal(request)
    if portal is None:
        return redirect(home_url_for(user))

    has_profile = (
        user.has_teacher_profile if portal == "teacher" else user.has_student_profile
    )
    if has_profile or portal == user.role:
        # Nothing to confirm - either they already have it (an old
        # bookmarked link) or they're asking for the portal they're
        # already on.
        return redirect(ROLE_HOME[portal])

    return render(request, "web/add_role.html", {"portal": portal})


def staff_login_page(request):
    """Unlinked staff sign-in (admin approval flow + direct super-admin)."""
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(request, "web/login_staff.html", {"page_title": "Staff sign-in"})


# ----------------------------------------------------------------------
# Hidden staff gateway - reached only by triple-clicking/triple-tapping the
# logo on the landing page (templates/web/landing.html). Never linked from
# any nav. See StaffSuperAdminLoginView / StaffAdminLoginView in
# apps.accounts.admin_api for the endpoints these pages post to.
# ----------------------------------------------------------------------
def staff_gateway_page(request):
    """Three options: create an admin account, log in as admin, log in as super admin."""
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(request, "web/staff/gateway.html", {"page_title": "Staff access"})


def staff_login_superadmin_page(request):
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(
        request, "web/staff/login_superadmin.html", {"page_title": "Super Admin sign-in"}
    )


def staff_login_admin_page(request):
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(
        request, "web/staff/login_admin.html", {"page_title": "Admin sign-in"}
    )


def staff_create_admin_account_page(request):
    """Self-service "become an Admin" request form (Phase 3)."""
    user = resolve_web_user(request)
    if user is not None:
        return redirect(home_url_for(user))
    return render(
        request,
        "web/staff/create_admin_account.html",
        {"page_title": "Request admin access"},
    )


@role_required("teacher")
def teacher_profile(request):
    """
    The teaching profile, with one escape hatch.

    The SPA owns this page, but identity verification — document upload,
    selfie liveness, the video-interview request — still lives in the Django
    template and gates whether a teacher is visible at all. Rather than port
    a security-sensitive upload flow in the same pass, ?legacy=1 serves the
    original page so verification stays reachable and working.
    """
    from apps.web.vite import spa_assets

    if request.GET.get("legacy") == "1":
        return render(
            request,
            "web/teacher/profile.html",
            {
                "page_title": "Verification",
                "page_desc": "Identity checks. The rest of your profile has moved.",
            },
        )

    assets = spa_assets()
    return render(
        request,
        "web/app_shell.html",
        {
            "page_title": "Your teaching profile",
            "page_desc": "This is what students see.",
            "spa_js": assets["js"],
            "spa_css": assets["css"],
            "spa_built": assets["built"],
        },
    )


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


def spa(*, roles, title, desc=""):
    """
    A page owned by the React app instead of a Django template.

    Identical guard story to page(): role_required still decides who may see
    the shell, and the DRF API still re-authorises every call the browser
    makes. The only difference is that the body is mounted by React rather
    than rendered here, so pages can move across one at a time.
    """
    from apps.web.vite import spa_assets

    @role_required(*roles)
    def view(request, **kwargs):
        assets = spa_assets()
        ctx = {
            "page_title": title,
            "page_desc": desc,
            "spa_js": assets["js"],
            "spa_css": assets["css"],
            "spa_built": assets["built"],
        }
        ctx.update(kwargs)
        return render(request, "web/app_shell.html", ctx)

    view.__name__ = "spa_" + title.lower().replace(" ", "_")
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
