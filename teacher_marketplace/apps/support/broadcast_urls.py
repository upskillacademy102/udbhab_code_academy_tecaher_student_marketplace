from django.urls import path

from apps.support.broadcast_views import AdminBroadcastMessageListCreateView

app_name = "admin_broadcast"

urlpatterns = [
    path("", AdminBroadcastMessageListCreateView.as_view(), name="list-create"),
]
