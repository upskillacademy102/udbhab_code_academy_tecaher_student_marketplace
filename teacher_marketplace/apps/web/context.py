"""Template context shared by every page."""

from django.conf import settings

from apps.web.guards import ROLE_HOME


def site(request):
    web_user = getattr(request, "web_user", None)
    role = getattr(web_user, "role", None)
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_TAGLINE": settings.SITE_TAGLINE,
        "API_BASE_URL": settings.API_BASE_URL,
        "web_user": web_user,
        "web_role": role,
        "web_home": ROLE_HOME.get(role, "/"),
    }
