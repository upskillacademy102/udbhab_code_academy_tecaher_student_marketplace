from django.urls import path

from apps.support.admin_views import (
    AdminSupportTicketAssignView,
    AdminSupportTicketListView,
    AdminSupportTicketResolveView,
)

app_name = "admin_support"

urlpatterns = [
    path("", AdminSupportTicketListView.as_view(), name="list"),
    path("<uuid:id>/assign/", AdminSupportTicketAssignView.as_view(), name="assign"),
    path("<uuid:id>/resolve/", AdminSupportTicketResolveView.as_view(), name="resolve"),
]
