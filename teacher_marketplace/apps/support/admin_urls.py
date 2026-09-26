from django.urls import path

from apps.support.admin_views import (
    AdminSupportTicketAcceptView,
    AdminSupportTicketAssignView,
    AdminSupportTicketListView,
    AdminSupportTicketResolveView,
)

app_name = "admin_support"

urlpatterns = [
    path("", AdminSupportTicketListView.as_view(), name="list"),
    path("<uuid:id>/assign/", AdminSupportTicketAssignView.as_view(), name="assign"),
    path("<uuid:id>/accept/", AdminSupportTicketAcceptView.as_view(), name="accept"),
    path("<uuid:id>/resolve/", AdminSupportTicketResolveView.as_view(), name="resolve"),
]
