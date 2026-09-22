"""
Root URL configuration for the Teacher Marketplace Platform.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.lead_engine.urls import (
    lead_unlock_pricing_urlpatterns,
    teacher_best_slots_urlpatterns,
)
from apps.payments.urls import payment_urlpatterns, token_package_urlpatterns
from apps.reviews.urls import review_urlpatterns, teacher_reviews_urlpatterns
from apps.student_requirement.urls import me_preferences_urlpatterns
from apps.teacher_profile.urls import me_availability_urlpatterns
from apps.trust.urls import appeal_urlpatterns, safety_urlpatterns

api_v1_patterns = [
    path("public/", include("apps.web.api_urls")),
    path("auth/", include("apps.accounts.urls")),
    path("verify/", include("apps.trust.urls")),
    path("support/", include("apps.support.urls")),
    path("safety/", include((safety_urlpatterns, "trust"), namespace="safety")),
    path("appeals/", include((appeal_urlpatterns, "trust"), namespace="appeals")),
    path("admin/users/", include("apps.accounts.admin_users_urls")),
    path("admin/teacher-profiles/", include("apps.teacher_profile.admin_urls")),
    path(
        "admin/onboarding-calls/",
        include("apps.teacher_profile.onboarding_call_urls"),
    ),
    path("admin/support-tickets/", include("apps.support.admin_urls")),
    path("ops/", include("apps.ops.urls")),
    path("lp/", include("apps.learning_partner.urls")),
    path("students/", include("apps.students.urls")),
    path(
        "students/me/preferences/",
        include(
            (me_preferences_urlpatterns, "student_requirement"),
            namespace="students-me-preferences",
        ),
    ),
    path("teachers/", include("apps.teachers.urls")),
    path(
        "teachers/",
        include(
            (teacher_best_slots_urlpatterns, "lead_engine"),
            namespace="teacher-best-slots",
        ),
    ),
    path(
        "teachers/",
        include((teacher_reviews_urlpatterns, "reviews"), namespace="teacher-reviews"),
    ),
    path(
        "teachers/me/",
        include(
            (me_availability_urlpatterns, "teacher_profile"), namespace="teachers-me"
        ),
    ),
    path("teachers/profile/", include("apps.teacher_profile.urls")),
    path("subjects/", include("apps.subjects.urls")),
    path("languages/", include("apps.languages.urls")),
    path("grade-levels/", include("apps.grade_levels.urls")),
    path("location/", include("apps.location.urls")),
    path("student-requirements/", include("apps.student_requirement.urls")),
    path("leads/", include("apps.lead_engine.urls")),
    path(
        "lead-unlock-pricing/",
        include(
            (lead_unlock_pricing_urlpatterns, "lead_engine"),
            namespace="lead-unlock-pricing",
        ),
    ),
    path("search/", include("apps.search.urls")),
    path("wallet/", include("apps.wallet.urls")),
    path(
        "token-packages/",
        include((token_package_urlpatterns, "payments"), namespace="token-packages"),
    ),
    path("payments/", include((payment_urlpatterns, "payments"), namespace="payments")),
    path("subscriptions/", include("apps.subscriptions.urls")),
    path("reviews/", include((review_urlpatterns, "reviews"), namespace="reviews")),
    path("notifications/", include("apps.notifications.urls")),
    path("dashboard/", include("apps.analytics.urls")),
    path("matching/", include("apps.matching.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1_patterns)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Server-rendered frontend (app shell + route guards). Must be last so
    # it never shadows /admin/, /api/... .
    path("", include("apps.web.urls")),
]

# Friendly branded error pages for the whole site.
handler403 = "apps.web.views.handler403"
handler404 = "apps.web.views.handler404"
handler500 = "apps.web.views.handler500"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
