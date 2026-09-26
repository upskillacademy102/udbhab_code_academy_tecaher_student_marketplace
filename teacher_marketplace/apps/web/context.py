"""Template context shared by every page."""

from django.conf import settings

from apps.web.guards import home_url_for


def site(request):
    web_user = getattr(request, "web_user", None)
    role = getattr(web_user, "role", None)
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_TAGLINE": settings.SITE_TAGLINE,
        "API_BASE_URL": settings.API_BASE_URL,
        "web_user": web_user,
        "web_role": role,
        "web_department_slug": getattr(
            getattr(web_user, "admin_department", None), "slug", None
        ),
        "web_home": home_url_for(web_user),
        "web_has_student_profile": bool(getattr(web_user, "has_student_profile", False)),
        "web_has_teacher_profile": bool(getattr(web_user, "has_teacher_profile", False)),
    }
