"""
URL configuration for the teacher_profile app.

Included from config/urls.py at the `api/v1/teachers/profile/`
prefix. NEW in this phase: also included a second time at
`api/v1/teachers/me/` (see config/urls.py patch below), so the new
structured availability endpoints are reachable at BOTH:

    /api/v1/teachers/profile/availability/          (legacy path,
        pre-existing prefix - kept working)
    /api/v1/teachers/me/availability/                (the path this
        spec explicitly lists)

Both resolve to the SAME views - this is a deliberate dual-mount,
not duplicated code, to satisfy the new spec's exact endpoint list
without breaking any existing API consumer built against the
original /teachers/profile/ prefix from Phase 2.
"""

from django.urls import path

from apps.teacher_profile.verification_views import (
    TeacherVerificationSubmitView,
    TeacherVerificationView,
)
from apps.teacher_profile.views import (
    TeacherAvailabilityDetailView,
    TeacherAvailabilityListCreateView,
    TeacherProfileView,
    TeacherScheduleExceptionDetailView,
    TeacherScheduleExceptionListCreateView,
    TeacherWeeklyAvailabilityDetailView,
    TeacherWeeklyAvailabilityListCreateView,
)

app_name = "teacher_profile"

urlpatterns = [
    path("", TeacherProfileView.as_view(), name="my-marketplace-profile"),
    path(
        "availability/",
        TeacherAvailabilityListCreateView.as_view(),
        name="availability-list-create",
    ),
    path(
        "availability/<uuid:id>/",
        TeacherAvailabilityDetailView.as_view(),
        name="availability-detail",
    ),
    path(
        "weekly-availability/",
        TeacherWeeklyAvailabilityListCreateView.as_view(),
        name="weekly-availability-list-create",
    ),
    path(
        "weekly-availability/<uuid:id>/",
        TeacherWeeklyAvailabilityDetailView.as_view(),
        name="weekly-availability-detail",
    ),
    path(
        "schedule-exceptions/",
        TeacherScheduleExceptionListCreateView.as_view(),
        name="schedule-exception-list-create",
    ),
    path(
        "schedule-exceptions/<uuid:id>/",
        TeacherScheduleExceptionDetailView.as_view(),
        name="schedule-exception-detail",
    ),
    path("verification/", TeacherVerificationView.as_view(), name="verification"),
    path(
        "verification/<str:key>/submit/",
        TeacherVerificationSubmitView.as_view(),
        name="verification-submit",
    ),
]

# Second URL pattern list, for mounting the SAME weekly-availability
# views at the spec's exact required path: /api/v1/teachers/me/availability/
me_availability_urlpatterns = [
    path(
        "availability/",
        TeacherWeeklyAvailabilityListCreateView.as_view(),
        name="me-weekly-availability-list-create",
    ),
    path(
        "availability/<uuid:id>/",
        TeacherWeeklyAvailabilityDetailView.as_view(),
        name="me-weekly-availability-detail",
    ),
]
