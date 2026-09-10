from django.urls import path

from apps.support.views import MySupportTicketListCreateView

app_name = "support"

urlpatterns = [
    path("tickets/", MySupportTicketListCreateView.as_view(), name="ticket-list-create"),
]
