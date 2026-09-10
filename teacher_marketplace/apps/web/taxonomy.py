"""
The subject / language lists the public pages render.

WHY THIS IS NOT AN API CALL
    The obvious implementation — fetch /api/v1/subjects/ from the browser —
    does not work. Both taxonomy routes are registered as ``_ANY_AUTHED`` in
    apps/accounts/api_permissions.py, so they 401 for a logged-out visitor.
    (The view docstrings in apps/subjects/views.py claim they are public;
    the permission registry is the real boundary and it disagrees.)

    Reading the models here instead is also simply better for a
    server-rendered page: the options land in the initial HTML, so search
    engines see them — as a JavaScript array they were invisible.

ORDERING
    By how many teachers actually teach the subject / teach in the language,
    then by name. A marketplace should lead with what it can serve, not with
    whatever sorts first alphabetically. With no teachers yet, every count is
    zero and this degrades to alphabetical, which is the current reality.

CACHING
    Five minutes, mirroring apps/web/api_views.py's landing-stats cache.
    A Super Admin adding a subject at /super-admin/subjects/ appears on the
    landing page within that window with no deploy. Any failure degrades to
    empty lists, and the picker renders its free-text form rather than
    breaking the page.
"""

from django.core.cache import cache
from django.db.models import Count, Q

_CACHE_KEY = "public:taxonomy:v1"
_CACHE_TTL = 300  # seconds


def _compute() -> dict:
    from apps.languages.models import Language
    from apps.subjects.models import Subject

    def ranked(model):
        return list(
            model.objects.filter(is_active=True)
            .annotate(
                supply=Count(
                    "teacher_profiles",
                    filter=Q(teacher_profiles__is_deleted=False),
                    distinct=True,
                )
            )
            .order_by("-supply", "name")
            .values_list("name", flat=True)
        )

    return {"subjects": ranked(Subject), "languages": ranked(Language)}


def public_taxonomy() -> dict:
    """``{"subjects": [name, ...], "languages": [name, ...]}`` — never raises."""
    data = cache.get(_CACHE_KEY)
    if data is None:
        try:
            data = _compute()
        except Exception:  # noqa: BLE001 - taxonomy must never break a public page
            data = {"subjects": [], "languages": []}
        cache.set(_CACHE_KEY, data, _CACHE_TTL)
    return data
