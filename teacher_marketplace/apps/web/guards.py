"""
Route protection for the server-rendered frontend.

The **security boundary is still the DRF API** (every data call the browser
makes is re-authorised by RoleBasedAPIPermission). These guards exist so a
user never *sees* a page they cannot use, and so a hand-typed forbidden URL
returns a friendly 403 instead of a broken page.

User identity is resolved from the same httpOnly `access` cookie the API
uses (apps.accounts.authentication.CookieJWTAuthentication), so the frontend
and API always agree on who is logged in.
"""

from functools import wraps
from urllib.parse import quote

from django.shortcuts import redirect, render

from apps.accounts.authentication import CookieJWTAuthentication

ROLE_HOME = {
    "student": "/student/",
    "teacher": "/teacher/",
    # Repointed to the new React dashboards (Phase 4). The old
    # /admin-portal/ and /super-admin/ templates still work by direct URL -
    # they're just no longer where a staff login lands.
    "admin": "/staff/admin/",
    "superadmin": "/staff/superadmin/",
}


def resolve_web_user(request):
    """Return the User for the request's auth cookie, or None."""
    try:
        result = CookieJWTAuthentication().authenticate(request)
    except Exception:
        return None
    if not result:
        return None
    return result[0]


def home_url_for(user):
    if getattr(user, "is_learning_partner_admin", False):
        return "/staff/learning-partner/"
    return ROLE_HOME.get(getattr(user, "role", None), "/")


def suspended_needs_appeal_page(user) -> bool:
    """
    True when a risk-suspended user should be bounced to /suspended/.
    A no-op unless BOTH ``TRUST_ENABLE_RISK_AUTO_ACTIONS`` (so a
    suspension can exist) and ``TRUST_ENABLE_SUSPENSION_APPEALS`` (so we
    surface the appeal page) are on.
    """
    from django.conf import settings

    if not getattr(settings, "TRUST_ENABLE_SUSPENSION_APPEALS", False):
        return False
    try:
        from apps.trust.services.risk_service import RiskService

        return bool(RiskService.is_suspended(user))
    except Exception:  # noqa: BLE001 - never let this break page rendering
        return False


def _login_redirect(request):
    return redirect(f"/login/?next={quote(request.get_full_path())}")


def login_required_web(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = resolve_web_user(request)
        if user is None:
            return _login_redirect(request)
        request.web_user = user
        return view(request, *args, **kwargs)

    return wrapped


def role_required(*roles):
    """
    Allow only the given roles. superadmin is implicitly allowed everywhere
    (mirrors the API's Super Admin rule), unless roles == ("superadmin",).
    """
    allowed = set(roles)
    if allowed != {"superadmin"}:
        allowed.add("superadmin")

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = resolve_web_user(request)
            if user is None:
                return _login_redirect(request)
            request.web_user = user
            if user.role not in allowed:
                return render(
                    request,
                    "web/errors/403.html",
                    {"home_url": home_url_for(user)},
                    status=403,
                )
            if not request.path.startswith(
                "/suspended"
            ) and suspended_needs_appeal_page(user):
                return redirect("/suspended/")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def learning_partner_required(view):
    """
    Like role_required("admin"), but ALSO requires the admin's department
    to be the Learning Partner one - a plain admin (or superadmin, who
    bypasses role_required everywhere else) gets a clean 403 here rather
    than a broken-looking SPA shell whose data calls all 403 underneath it.
    """

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = resolve_web_user(request)
        if user is None:
            return _login_redirect(request)
        request.web_user = user
        if not user.is_learning_partner_admin:
            return render(
                request,
                "web/errors/403.html",
                {"home_url": home_url_for(user)},
                status=403,
            )
        return view(request, *args, **kwargs)

    return wrapped
