from django.urls import path

from apps.teacher_profile.onboarding_call_views import (
    AdminOnboardingCallAcceptView,
    AdminOnboardingCallListView,
    AdminOnboardingCallScheduleView,
)

app_name = "admin_onboarding_calls"

urlpatterns = [
    path("", AdminOnboardingCallListView.as_view(), name="list"),
    path("<uuid:id>/accept/", AdminOnboardingCallAcceptView.as_view(), name="accept"),
    path(
        "<uuid:id>/schedule/",
        AdminOnboardingCallScheduleView.as_view(),
        name="schedule",
    ),
]
