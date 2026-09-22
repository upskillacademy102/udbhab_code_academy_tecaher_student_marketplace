from django.urls import path

from apps.learning_partner.views import (
    LPAuditView,
    LPDashboardView,
    LPEndorseFakeReportView,
    LPFakeLeadReportsView,
    LPStudentDetailView,
    LPStudentLeadQualityView,
    LPStudentListView,
    LPTaxonomyRequestListCreateView,
    LPTeacherDetailView,
    LPTeacherLeadReviewsView,
    LPTeacherListView,
)

app_name = "lp"

urlpatterns = [
    path("dashboard/", LPDashboardView.as_view(), name="dashboard"),
    path("students/", LPStudentListView.as_view(), name="student-list"),
    path("students/<uuid:id>/", LPStudentDetailView.as_view(), name="student-detail"),
    path("teachers/", LPTeacherListView.as_view(), name="teacher-list"),
    path("teachers/<uuid:id>/", LPTeacherDetailView.as_view(), name="teacher-detail"),
    path(
        "taxonomy-requests/",
        LPTaxonomyRequestListCreateView.as_view(),
        name="taxonomy-request-list-create",
    ),
    path(
        "fake-lead-reports/",
        LPFakeLeadReportsView.as_view(),
        name="fake-lead-reports",
    ),
    path(
        "fake-lead-reports/<uuid:student_id>/endorse/",
        LPEndorseFakeReportView.as_view(),
        name="fake-lead-report-endorse",
    ),
    path(
        "students-lead-quality/",
        LPStudentLeadQualityView.as_view(),
        name="students-lead-quality",
    ),
    path(
        "teacher-lead-reviews/",
        LPTeacherLeadReviewsView.as_view(),
        name="teacher-lead-reviews",
    ),
    path("audit/", LPAuditView.as_view(), name="audit"),
]
