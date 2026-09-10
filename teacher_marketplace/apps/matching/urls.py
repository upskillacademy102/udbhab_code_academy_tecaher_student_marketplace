from django.urls import path

from apps.matching.views import (
    AcceptAssignmentView,
    EligibleTeacherSearchView,
    LanguageAliasListCreateView,
    MatchingConfigListCreateView,
    MyLeadAssignmentsView,
    PincodeLocationListCreateView,
    RejectAssignmentView,
    SubjectAliasListCreateView,
)

app_name = "matching"

urlpatterns = [
    path(
        "search/teachers/", EligibleTeacherSearchView.as_view(), name="eligible-search"
    ),
    path("assignments/", MyLeadAssignmentsView.as_view(), name="my-assignments"),
    path(
        "assignments/<uuid:id>/accept/",
        AcceptAssignmentView.as_view(),
        name="assignment-accept",
    ),
    path(
        "assignments/<uuid:id>/reject/",
        RejectAssignmentView.as_view(),
        name="assignment-reject",
    ),
    path(
        "pincode-locations/",
        PincodeLocationListCreateView.as_view(),
        name="pincode-list-create",
    ),
    path(
        "subject-aliases/",
        SubjectAliasListCreateView.as_view(),
        name="subject-alias-list-create",
    ),
    path(
        "language-aliases/",
        LanguageAliasListCreateView.as_view(),
        name="language-alias-list-create",
    ),
    path("config/", MatchingConfigListCreateView.as_view(), name="config-list-create"),
]
