"""
Shared JWT-pair minting. Used by login, admin-login approval and
impersonation so every access/refresh token carries the same base
claims (email / role / full_name / sid) plus whatever extra claims the
caller needs (e.g. the `act` impersonation marker).
"""

from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import SESSION_CLAIM


def issue_pair(user, *, sid, extra_claims=None):
    """Return (access_str, refresh_str) for `user`, bound to session id `sid`."""
    refresh = RefreshToken.for_user(user)
    refresh["email"] = user.email
    refresh["role"] = user.role
    refresh["full_name"] = user.get_full_name()
    refresh[SESSION_CLAIM] = str(sid)
    for key, value in (extra_claims or {}).items():
        refresh[key] = value
    return str(refresh.access_token), str(refresh)
