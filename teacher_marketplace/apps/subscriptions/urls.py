"""
URL configuration for the subscriptions app.

Included from config/urls.py at the `api/v1/subscriptions/`
prefix, so the full paths resolve to:

    GET/POST                /api/v1/subscriptions/plans/
    GET/PUT/PATCH/DELETE     /api/v1/subscriptions/plans/{id}/
    GET                      /api/v1/subscriptions/
    POST                     /api/v1/subscriptions/activate/
    GET                      /api/v1/subscriptions/quota/
"""

from django.urls import path

from apps.subscriptions.views import (
    ActivateSubscriptionView,
    MyLeadQuotaView,
    MySubscriptionView,
    SubscriptionPlanDetailView,
    SubscriptionPlanListCreateView,
)

app_name = "subscriptions"

urlpatterns = [
    path("", MySubscriptionView.as_view(), name="my-subscription"),
    path("activate/", ActivateSubscriptionView.as_view(), name="activate"),
    path("quota/", MyLeadQuotaView.as_view(), name="my-quota"),
    path("plans/", SubscriptionPlanListCreateView.as_view(), name="plan-list-create"),
    path("plans/<uuid:id>/", SubscriptionPlanDetailView.as_view(), name="plan-detail"),
]
