"""
Centralised role -> HTTP-method -> endpoint authorisation registry.

Single source of truth for "which role may call which API with which HTTP
method". Enforced globally by ``RoleBasedAPIPermission``
(``apps.accounts.permissions``), which is installed in
``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` right after
``IsAuthenticated``.

    REQUEST
      -> authenticate (apps.accounts.authentication)   -> 401 on failure
      -> identify user + role
      -> RoleBasedAPIPermission -> is_allowed(role, method, route_name)
      -> ALLOW (run view) or DENY (403)

Design rules (all mandatory, per the approved permission matrix):

  * Keyed by URL **route name** (``request.resolver_match.view_name`` ==
    ``"namespace:name"``). Stable, unambiguous, greppable, immune to
    UUID path params.

  * **DEFAULT DENY.** Any (role, method, route) triple not explicitly
    granted below is refused - including brand-new endpoints a developer
    forgets to register.

  * **HTTP method is part of the key.** A route may grant ``GET`` to
    every role while restricting ``DELETE`` to admins.

  * **Super Admin -> ALL APIs.** ``is_allowed`` short-circuits to True for
    the ``superadmin`` role on every route (authentication is still
    required upstream). Super Admin is the one documented exception to
    default-deny: a new, unregistered endpoint is allowed for Super Admin
    and denied for everyone else.

  * ``PUBLIC_ROUTE_NAMES`` - the few routes that skip the role check
    entirely (login, register, token refresh, password reset, the
    Razorpay webhook, the OpenAPI docs). Their views are ``AllowAny``.

Approved matrix: 2026-08-29. To change the policy, edit ``_RULES`` (and
``PUBLIC_ROUTE_NAMES`` if a route's public status changes). Nothing else
in the codebase needs to change.
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# Role vocabulary (mirrors apps.accounts.models.UserRole values)
# ----------------------------------------------------------------------
STUDENT = "student"
TEACHER = "teacher"
ADMIN = "admin"
SUPERADMIN = "superadmin"

ALL_ROLES = (STUDENT, TEACHER, ADMIN, SUPERADMIN)

# Role groups used when building the rule table. Super Admin is never
# listed - it is granted everything by the short-circuit in is_allowed().
_ANY_AUTHED = (STUDENT, TEACHER, ADMIN)  # every logged-in role
_TEACHER_ADMIN = (TEACHER, ADMIN)
_ADMIN = (ADMIN,)
_STUDENT = (STUDENT,)
_TEACHER = (TEACHER,)
_STUDENT_ADMIN = (STUDENT, ADMIN)
_STUDENT_TEACHER = (STUDENT, TEACHER)

_R = ("GET",)
_RW_DETAIL = ("GET", "PUT", "PATCH", "DELETE")


# ----------------------------------------------------------------------
# Routes that bypass the role check entirely (views are AllowAny).
# ----------------------------------------------------------------------
PUBLIC_ROUTE_NAMES = frozenset(
    {
        "accounts:register",
        "accounts:login",
        "accounts:token-refresh",
        "accounts:forgot-password",
        "accounts:reset-password",
        "accounts:admin-login",  # staff sign-in -> pending approval (no session issued)
        "accounts:admin-login-status",  # admin polls for approval (guarded by a one-time poll token)
        "public:stats",  # anonymous landing-page counts, no PII
        "payments:webhook",  # server-to-server, HMAC-verified
        "schema",  # OpenAPI - prod additionally gates to staff
        "swagger-ui",
        "redoc",
    }
)


# ----------------------------------------------------------------------
# The grant table: (route_name, (methods...), (roles...))
# Compiled into ROLE_API_PERMISSIONS at import time. Super Admin omitted
# throughout (handled by is_allowed's short-circuit).
# ----------------------------------------------------------------------
_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # ===== Auth / account - every authenticated role =======================
    ("accounts:logout", ("POST",), _ANY_AUTHED),
    ("accounts:change-password", ("POST",), _ANY_AUTHED),
    ("accounts:change-password-confirm", ("POST",), _ANY_AUTHED),
    ("accounts:change-email", ("POST",), _ANY_AUTHED),
    ("accounts:change-email-confirm", ("POST",), _ANY_AUTHED),
    ("accounts:change-mobile", ("POST",), _ANY_AUTHED),
    ("accounts:change-mobile-confirm", ("POST",), _ANY_AUTHED),
    ("accounts:sensitive-change-list", ("GET",), _ANY_AUTHED),
    ("accounts:sensitive-change-cancel", ("POST",), _ANY_AUTHED),
    ("accounts:me", ("GET", "PATCH"), _ANY_AUTHED),
    # ===== Contact verification (apps.trust) - own account, any role ========
    ("trust:verification-status", ("GET",), _ANY_AUTHED),
    ("trust:otp-email-request", ("POST",), _ANY_AUTHED),
    ("trust:otp-email-confirm", ("POST",), _ANY_AUTHED),
    ("trust:otp-mobile-request", ("POST",), _ANY_AUTHED),
    ("trust:otp-mobile-confirm", ("POST",), _ANY_AUTHED),
    # Report & block (Phase 8d) - any authenticated user
    ("safety:report-user", ("POST",), _ANY_AUTHED),
    ("safety:block-list", ("GET", "POST"), _ANY_AUTHED),
    ("safety:block-detail", ("DELETE",), _ANY_AUTHED),
    # Suspension appeals - own account, any authenticated role
    ("appeals:suspension", ("GET", "POST"), _ANY_AUTHED),
    ("appeals:suspension-withdraw", ("POST",), _ANY_AUTHED),
    # stop-impersonation is called *as the impersonated user* (any role)
    ("accounts:stop-impersonation", ("POST",), _ANY_AUTHED),
    # Dual-role: a Student/Teacher adding or switching to their other
    # portal. switch_active_role() itself rejects any target other than
    # student/teacher, so _ANY_AUTHED here is safe (mirrors stop-impersonation).
    ("accounts:switch-role", ("POST",), _ANY_AUTHED),
    # ===== User directory - Admin gets read-only; write/impersonate = Super Admin only ==
    ("admin_users:list", ("GET",), _ADMIN),
    ("admin_users:detail", ("GET",), _ADMIN),
    # ===== Teacher verification - Admin + Super Admin ======================
    ("admin_teacher_profiles:list", ("GET",), _ADMIN),
    ("admin_teacher_profiles:detail", ("GET",), _ADMIN),
    ("admin_teacher_profiles:verification", ("POST",), _ADMIN),
    ("admin_teacher_profiles:verification-item", ("POST",), _ADMIN),
    ("admin_onboarding_calls:list", ("GET",), _ADMIN),
    # ===== "Connect to Admin" support tickets ==============================
    # Filing a ticket is Student/Teacher only - Admin/Super Admin are the
    # people tickets get reported TO, not reporters themselves.
    ("support:ticket-list-create", ("GET", "POST"), _STUDENT_TEACHER),
    ("admin_support:list", ("GET",), _ADMIN),
    ("admin_support:resolve", ("POST",), _ADMIN),  # view itself 403s a non-assigned admin
    # POST admin_users:list, PATCH admin_users:detail, and admin_users:{activate,
    # deactivate,impersonate} + accounts:admin-login-{requests,approve,deny} +
    # admin_onboarding_calls:schedule + admin_support:assign + ops:* are
    # intentionally unlisted -> Super Admin only (is_allowed short-circuit).
    # ===== Notifications - every authenticated role ========================
    ("notifications:notification-list", ("GET",), _ANY_AUTHED),
    ("notifications:mark-read", ("POST",), _ANY_AUTHED),
    # ===== Dashboard - teacher + admin (role-aware view; no student view) ==
    ("analytics:dashboard", ("GET",), _TEACHER_ADMIN),
    # ======================================================================
    # STUDENT: own workspace
    # ======================================================================
    ("students:my-profile", ("GET", "POST", "PUT", "PATCH"), _STUDENT),
    ("student_requirement:requirement-list-create", ("GET", "POST"), _STUDENT),
    (
        "student_requirement:requirement-detail",
        ("GET", "PUT", "PATCH", "DELETE"),
        _STUDENT,
    ),
    ("student_requirement:preference-list-create", ("GET", "POST"), _STUDENT),
    ("student_requirement:preference-detail", ("PATCH", "DELETE"), _STUDENT),
    ("student_requirement:schedule-exception-list-create", ("GET", "POST"), _STUDENT),
    ("student_requirement:schedule-exception-detail", ("DELETE",), _STUDENT),
    ("student_requirement:direct-offer-create", ("POST",), _STUDENT),
    ("students-me-preferences:me-preference-list-create", ("GET", "POST"), _STUDENT),
    ("students-me-preferences:me-preference-detail", ("PATCH", "DELETE"), _STUDENT),
    # ======================================================================
    # PEOPLE SEARCH (search for *users*) - Admin only (+ Super Admin)
    # Student and Teacher may NEVER search students / arbitrary users.
    # ======================================================================
    ("students:student-list", ("GET",), _ADMIN),
    ("students:student-detail", ("GET",), _ADMIN),
    # ======================================================================
    # TEACHER DISCOVERY (student-facing "teacher search") - Student + Admin.
    # Teacher may NOT use teacher-marketplace search.
    # ======================================================================
    ("teachers:teacher-list", ("GET",), _STUDENT_ADMIN),
    ("teachers:teacher-detail", ("GET",), _STUDENT_ADMIN),
    ("teacher-best-slots:teacher-best-slots", ("GET",), _STUDENT_ADMIN),
    ("search:teacher-search", ("GET",), _STUDENT_ADMIN),
    ("search:teacher-marketplace-profile", ("GET",), _STUDENT_ADMIN),
    ("matching:eligible-search", ("GET",), _STUDENT_ADMIN),
    # ======================================================================
    # TEACHER: own workspace
    # ======================================================================
    ("teachers:my-profile", ("GET", "POST", "PUT", "PATCH"), _TEACHER),
    ("teachers:my-pincode", ("PATCH",), _TEACHER),
    (
        "teacher_profile:my-marketplace-profile",
        ("GET", "POST", "PUT", "PATCH"),
        _TEACHER,
    ),
    ("teacher_profile:verification", ("GET",), _TEACHER),
    ("teacher_profile:verification-submit", ("POST",), _TEACHER),
    ("teacher_profile:availability-list-create", ("GET", "POST"), _TEACHER),
    ("teacher_profile:availability-detail", ("DELETE",), _TEACHER),
    ("teacher_profile:weekly-availability-list-create", ("GET", "POST"), _TEACHER),
    ("teacher_profile:weekly-availability-detail", ("PATCH", "DELETE"), _TEACHER),
    ("teacher_profile:schedule-exception-list-create", ("GET", "POST"), _TEACHER),
    ("teacher_profile:schedule-exception-detail", ("DELETE",), _TEACHER),
    ("teachers-me:me-weekly-availability-list-create", ("GET", "POST"), _TEACHER),
    ("teachers-me:me-weekly-availability-detail", ("PATCH", "DELETE"), _TEACHER),
    # ======================================================================
    # TEACHER: marketplace workflow (leads / wallet / payments / subs)
    # ======================================================================
    ("lead_engine:lead-list", ("GET",), _TEACHER),
    ("lead_engine:lead-offers", ("GET",), _TEACHER),
    ("lead_engine:lead-detail", ("GET",), _TEACHER),
    ("lead_engine:lead-matches", ("GET",), _TEACHER),
    ("lead_engine:unlock-lead", ("POST",), _TEACHER),
    ("lead_engine:lead-rate", ("POST",), _TEACHER),
    ("lead_engine:lead-reject", ("POST",), _TEACHER),
    ("lead_engine:pending-ratings", ("GET",), _TEACHER),
    ("lead_engine:lead-export", ("GET",), _TEACHER),
    ("lead_engine:my-unlock-history", ("GET",), _TEACHER),
    # Reviews (Phase 8c) - students write/withdraw; anyone authed can read
    ("reviews:my-reviews", ("GET", "POST"), _STUDENT),
    ("reviews:review-detail", ("DELETE",), _STUDENT),
    ("teacher-reviews:teacher-reviews", ("GET",), _ANY_AUTHED),
    ("wallet:my-wallet", ("GET",), _TEACHER),
    ("wallet:wallet-history", ("GET",), _TEACHER),
    ("payments:payment-history", ("GET",), _TEACHER),
    ("payments:create-order", ("POST",), _TEACHER),
    ("payments:verify-payment", ("POST",), _TEACHER),
    ("subscriptions:my-subscription", ("GET",), _TEACHER),
    ("subscriptions:activate", ("POST",), _TEACHER),
    ("subscriptions:my-quota", ("GET",), _TEACHER),
    ("matching:my-assignments", ("GET",), _TEACHER),
    ("matching:assignment-accept", ("POST",), _TEACHER),
    ("matching:assignment-reject", ("POST",), _TEACHER),
    # ======================================================================
    # REFERENCE DATA - taxonomy: read = any authed role, write = admin
    # ======================================================================
    ("subjects:subject-list-create", ("GET",), _ANY_AUTHED),
    ("subjects:subject-list-create", ("POST",), _ADMIN),
    ("subjects:subject-detail", ("GET",), _ANY_AUTHED),
    ("subjects:subject-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("languages:language-list-create", ("GET",), _ANY_AUTHED),
    ("languages:language-list-create", ("POST",), _ADMIN),
    ("languages:language-detail", ("GET",), _ANY_AUTHED),
    ("languages:language-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("grade_levels:grade-level-list-create", ("GET",), _ANY_AUTHED),
    ("grade_levels:grade-level-list-create", ("POST",), _ADMIN),
    ("grade_levels:grade-level-detail", ("GET",), _ANY_AUTHED),
    ("grade_levels:grade-level-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("location:country-list-create", ("GET",), _ANY_AUTHED),
    ("location:country-list-create", ("POST",), _ADMIN),
    ("location:country-detail", ("GET",), _ANY_AUTHED),
    ("location:country-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("location:state-list-create", ("GET",), _ANY_AUTHED),
    ("location:state-list-create", ("POST",), _ADMIN),
    ("location:state-detail", ("GET",), _ANY_AUTHED),
    ("location:state-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("location:city-list-create", ("GET",), _ANY_AUTHED),
    ("location:city-list-create", ("POST",), _ADMIN),
    ("location:city-detail", ("GET",), _ANY_AUTHED),
    ("location:city-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    # ======================================================================
    # COMMERCIAL CATALOG - read = teacher + admin, write = admin
    # (students never buy tokens / subscribe / unlock leads)
    # ======================================================================
    ("token-packages:token-package-list-create", ("GET",), _TEACHER_ADMIN),
    ("token-packages:token-package-list-create", ("POST",), _ADMIN),
    ("token-packages:token-package-detail", ("GET",), _TEACHER_ADMIN),
    ("token-packages:token-package-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("subscriptions:plan-list-create", ("GET",), _TEACHER_ADMIN),
    ("subscriptions:plan-list-create", ("POST",), _ADMIN),
    ("subscriptions:plan-detail", ("GET",), _TEACHER_ADMIN),
    ("subscriptions:plan-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    ("lead-unlock-pricing:pricing-list-create", ("GET",), _TEACHER_ADMIN),
    ("lead-unlock-pricing:pricing-list-create", ("POST",), _ADMIN),
    ("lead-unlock-pricing:pricing-detail", ("GET",), _TEACHER_ADMIN),
    ("lead-unlock-pricing:pricing-detail", ("PUT", "PATCH", "DELETE"), _ADMIN),
    # ======================================================================
    # ADMIN CONFIGURATION - matching-engine internals, admin only
    # ======================================================================
    ("matching:pincode-list-create", ("GET", "POST"), _ADMIN),
    ("matching:subject-alias-list-create", ("GET", "POST"), _ADMIN),
    ("matching:language-alias-list-create", ("GET", "POST"), _ADMIN),
    ("matching:config-list-create", ("GET", "POST"), _ADMIN),
]


def _compile(rules) -> dict[str, dict[str, frozenset]]:
    table: dict[str, dict[str, set]] = {r: {} for r in ALL_ROLES}
    for route_name, methods, roles in rules:
        for role in roles:
            for method in methods:
                table[role].setdefault(method, set()).add(route_name)
    return {
        role: {method: frozenset(routes) for method, routes in methods.items()}
        for role, methods in table.items()
    }


#: ``{role: {HTTP_METHOD: frozenset(route_name, ...)}}`` - the compiled policy.
#: The ``superadmin`` entry is intentionally empty; see is_allowed().
ROLE_API_PERMISSIONS: dict[str, dict[str, frozenset]] = _compile(_RULES)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def is_public(route_name: str | None) -> bool:
    """True if the route bypasses the role check entirely."""
    return bool(route_name) and route_name in PUBLIC_ROUTE_NAMES


def is_allowed(role: str | None, method: str | None, route_name: str | None) -> bool:
    """
    Central authorisation decision. DEFAULT DENY.

    * Super Admin -> allowed on every route (including unregistered ones);
      authentication is enforced separately upstream.
    * Everyone else -> allowed only when the (role, method, route) triple
      is explicitly granted in ``_RULES``.
    """
    if not role or not method or not route_name:
        return False

    if role == SUPERADMIN:
        return True

    method = method.upper()
    # HEAD / OPTIONS ride along with a GET grant - browsers/DRF issue them
    # implicitly and they never mutate state.
    lookup_method = "GET" if method in ("HEAD", "OPTIONS") else method

    role_table = ROLE_API_PERMISSIONS.get(role)
    if not role_table:
        return False
    return route_name in role_table.get(lookup_method, frozenset())


def known_route_names() -> set[str]:
    """Every route name referenced by the registry (grants + public)."""
    names = set(PUBLIC_ROUTE_NAMES)
    for methods in ROLE_API_PERMISSIONS.values():
        for routes in methods.values():
            names.update(routes)
    return names
