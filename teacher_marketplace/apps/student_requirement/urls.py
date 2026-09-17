"""
URL configuration for the student_requirement app.

Included from config/urls.py at BOTH:
    /api/v1/student-requirements/    (existing Phase 2 prefix - CRUD
        for StudentRequirement itself, unchanged)
    /api/v1/students/me/preferences/  (new, spec-required path for
        StudentSchedulePreference CRUD specifically)

Same dual-mount reasoning as apps.teacher_profile.urls - see that
file's docstring.
"""

from django.urls import path

from apps.student_requirement.direct_offer_views import DirectOfferCreateView
from apps.student_requirement.views import (
    StudentRequirementDetailView,
    StudentRequirementListCreateView,
    StudentScheduleExceptionDetailView,
    StudentScheduleExceptionListCreateView,
    StudentSchedulePreferenceDetailView,
    StudentSchedulePreferenceListCreateView,
)

app_name = "student_requirement"

urlpatterns = [
    path(
        "", StudentRequirementListCreateView.as_view(), name="requirement-list-create"
    ),
    path(
        "preferences/",
        StudentSchedulePreferenceListCreateView.as_view(),
        name="preference-list-create",
    ),
    path(
        "preferences/<uuid:id>/",
        StudentSchedulePreferenceDetailView.as_view(),
        name="preference-detail",
    ),
    path(
        "schedule-exceptions/",
        StudentScheduleExceptionListCreateView.as_view(),
        name="schedule-exception-list-create",
    ),
    path(
        "schedule-exceptions/<uuid:id>/",
        StudentScheduleExceptionDetailView.as_view(),
        name="schedule-exception-detail",
    ),
    path(
        "direct-offer/", DirectOfferCreateView.as_view(), name="direct-offer-create"
    ),
    path(
        "<uuid:id>/", StudentRequirementDetailView.as_view(), name="requirement-detail"
    ),
]

# Mounted separately at /api/v1/students/me/preferences/ per the spec's exact required path.
me_preferences_urlpatterns = [
    path(
        "",
        StudentSchedulePreferenceListCreateView.as_view(),
        name="me-preference-list-create",
    ),
    path(
        "<uuid:id>/",
        StudentSchedulePreferenceDetailView.as_view(),
        name="me-preference-detail",
    ),
]
