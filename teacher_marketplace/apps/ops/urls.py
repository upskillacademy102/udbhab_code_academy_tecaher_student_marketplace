from django.urls import path

from apps.ops.views import (
    AuditEventListView,
    OpsErrorsView,
    OpsFakeLeadReportsView,
    OpsHealthView,
    OpsOverviewView,
    OpsRiskView,
    OpsSanctionLiftView,
    OpsSanctionListCreateView,
    OpsStudentLeadQualityView,
    OpsTeacherLeadReviewsView,
    ReviewQueueAssignView,
    ReviewQueueListView,
    ReviewQueueResolveView,
)

app_name = "ops"

urlpatterns = [
    path("events/", AuditEventListView.as_view(), name="events"),
    path("overview/", OpsOverviewView.as_view(), name="overview"),
    path("health/", OpsHealthView.as_view(), name="health"),
    path("errors/", OpsErrorsView.as_view(), name="errors"),
    path("review-queue/", ReviewQueueListView.as_view(), name="review-queue"),
    path(
        "review-queue/<uuid:id>/resolve/",
        ReviewQueueResolveView.as_view(),
        name="review-queue-resolve",
    ),
    path(
        "review-queue/<uuid:id>/assign/",
        ReviewQueueAssignView.as_view(),
        name="review-queue-assign",
    ),
    path("risk/", OpsRiskView.as_view(), name="risk"),
    path(
        "fake-lead-reports/",
        OpsFakeLeadReportsView.as_view(),
        name="fake-lead-reports",
    ),
    path("sanctions/", OpsSanctionListCreateView.as_view(), name="sanctions"),
    path(
        "sanctions/<uuid:id>/lift/",
        OpsSanctionLiftView.as_view(),
        name="sanction-lift",
    ),
    path(
        "students-lead-quality/",
        OpsStudentLeadQualityView.as_view(),
        name="students-lead-quality",
    ),
    path(
        "teacher-lead-reviews/",
        OpsTeacherLeadReviewsView.as_view(),
        name="teacher-lead-reviews",
    ),
]
