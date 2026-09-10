"""
The one public JSON endpoint apps.web owns — everywhere else in this app
renders HTML only (see the module docstring in views.py). Feeds the
landing page's "why choose us" numbers with real, live counts (no PII,
aggregate only) instead of an invented statistic.

    GET /api/v1/public/stats/   no auth required
"""

from django.core.cache import cache
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from apps.core.responses import APIResponse

_CACHE_KEY = "public:landing-stats"
_CACHE_TTL = 300  # 5 minutes - these numbers don't need to be second-fresh


def _compute_stats() -> dict:
    from apps.accounts.models import User, UserRole
    from apps.subjects.models import Subject
    from apps.teacher_profile.models import TeacherProfile, VerificationStatus

    return {
        "verified_teachers": TeacherProfile.objects.filter(
            verification_status=VerificationStatus.VERIFIED
        ).count(),
        "subjects": Subject.objects.count(),
        "students": User.objects.filter(
            role=UserRole.STUDENT, is_active=True
        ).count(),
    }


@extend_schema(
    tags=["Public"],
    summary="Live platform counts for the landing page (no auth)",
    responses={
        200: OpenApiResponse(
            description="`data`: {verified_teachers, subjects, students}."
        )
    },
)
class PublicStatsView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        data = cache.get(_CACHE_KEY)
        if data is None:
            try:
                data = _compute_stats()
            except Exception:  # noqa: BLE001 - a stats hiccup must never break the landing page
                data = {"verified_teachers": 0, "subjects": 0, "students": 0}
            cache.set(_CACHE_KEY, data, _CACHE_TTL)
        return APIResponse.success(data=data)
