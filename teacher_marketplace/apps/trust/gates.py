"""
DRF permission classes that gate an action on the caller having a
verified contact. **Each is a no-op while its feature flag is OFF** - the
default - so wiring them into a view changes nothing until the flag is
switched on.

Usage on a view:

    from apps.trust.gates import default_permissions_with

    class SomeView(APIView):
        permission_classes = default_permissions_with(
            RequireVerifiedEmail, RequireVerifiedMobile
        )
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.accounts.permissions import RoleBasedAPIPermission


class RequireVerifiedEmail(BasePermission):
    message = "Please verify your email address before doing this."

    def has_permission(self, request, view):
        if not getattr(settings, "TRUST_REQUIRE_EMAIL_VERIFICATION", False):
            return True
        user = getattr(request, "user", None)
        # Unauthenticated requests are handled by IsAuthenticated (401);
        # don't turn them into a 403 here.
        return not (user and user.is_authenticated) or bool(user.is_email_verified)


class RequireVerifiedMobile(BasePermission):
    message = "Please verify your mobile number before doing this."

    def has_permission(self, request, view):
        if not getattr(settings, "TRUST_REQUIRE_MOBILE_VERIFICATION", False):
            return True
        user = getattr(request, "user", None)
        return not (user and user.is_authenticated) or bool(user.is_mobile_verified)


class RequireVerifiedToPostRequirement(BasePermission):
    message = "Verify your email and mobile number before posting a requirement."

    def has_permission(self, request, view):
        from rest_framework.permissions import SAFE_METHODS

        if request.method in SAFE_METHODS:
            return True
        if not getattr(settings, "TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST", False):
            return True
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return True
        return bool(user.is_email_verified and user.is_mobile_verified)


class NotRiskSuspended(BasePermission):
    message = (
        "Your account is temporarily suspended while our team reviews recent "
        "activity. Contact support if you think this is a mistake."
    )

    def has_permission(self, request, view):
        from rest_framework.permissions import SAFE_METHODS

        if request.method in SAFE_METHODS:
            return True
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return True
        from apps.trust.services.risk_service import RiskService

        return not RiskService.is_suspended(user)


class NotFlaggedAsDuplicate(BasePermission):
    message = (
        "Your account is under review because it looks like a duplicate of another "
        "account. Contact support to resolve this."
    )

    def has_permission(self, request, view):
        if not getattr(settings, "TRUST_ENABLE_DEDUP_BLOCKING", False):
            return True
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return True
        from apps.trust.services.dedupe_service import DedupeService

        return not DedupeService.is_blocked(user)


def default_permissions_with(*extra):
    """The project's default permission stack plus the given gate classes."""
    return [IsAuthenticated, RoleBasedAPIPermission, *extra]
