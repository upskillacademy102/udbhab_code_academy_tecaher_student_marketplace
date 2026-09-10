"""
"Connect to Admin" - the Admin / Super-Admin side ("Bugs Reported").

    GET  /api/v1/admin/support-tickets/                list + filter   (admin, superadmin)
    POST /api/v1/admin/support-tickets/{id}/assign/     one or more admins  (superadmin only)
    POST /api/v1/admin/support-tickets/{id}/resolve/    resolve / dismiss   (assigned admin, or superadmin)
"""

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.core.exceptions.custom_exceptions import (
    PermissionDeniedException,
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.support.models import SupportTicket
from apps.support.serializers import AdminSupportTicketSerializer
from apps.support.services import SupportService


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _get_ticket_or_404(ticket_id):
    ticket = SupportTicket.objects.filter(id=ticket_id).first()
    if ticket is None:
        raise ResourceNotFoundException(detail="Ticket not found.")
    return ticket


@extend_schema(
    tags=["Support"],
    parameters=[
        OpenApiParameter(
            "status",
            str,
            OpenApiParameter.QUERY,
            description="Pass 'all' to include resolved/closed tickets; "
            "default shows only open + assigned.",
        ),
        OpenApiParameter(
            "mine",
            str,
            OpenApiParameter.QUERY,
            description="Pass '1' to show only tickets assigned to the current user.",
        ),
    ],
    responses=AdminSupportTicketSerializer(many=True),
)
class AdminSupportTicketListView(generics.ListAPIView):
    serializer_class = AdminSupportTicketSerializer
    pagination_class = _Pagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportTicket.objects.none()
        qs = SupportTicket.objects.select_related("reporter").prefetch_related(
            "attachments", "assigned_admins"
        )
        p = self.request.query_params
        if p.get("status") != "all":
            qs = qs.filter(status__in=["open", "assigned"])
        if p.get("mine") == "1":
            qs = qs.filter(assigned_admins=self.request.user)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return APIResponse.paginated(
                data=serializer.data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        return APIResponse.success(data=serializer.data)


@extend_schema(
    tags=["Support"],
    summary="Super Admin: assign one or more Admins to a ticket",
    request=inline_serializer(
        "SupportTicketAssign",
        {"assigned_admin_ids": serializers.ListField(child=serializers.UUIDField())},
    ),
    responses={200: OpenApiResponse(description="`data`: the updated ticket.")},
)
class AdminSupportTicketAssignView(APIView):
    """Not granted to plain Admin in apps.accounts.api_permissions - left
    unlisted so only Super Admin (the is_allowed() short-circuit) can call
    it, same idiom as admin_onboarding_calls:schedule."""

    def post(self, request, id):
        from apps.accounts.models import User

        ticket = _get_ticket_or_404(id)
        ids = request.data.get("assigned_admin_ids")
        if not ids or not isinstance(ids, list):
            raise ValidationException(detail="Choose at least one Admin to assign.")

        admins = list(
            User.objects.filter(
                id__in=ids,
                role__in=[UserRole.ADMIN, UserRole.SUPERADMIN],
                is_active=True,
            )
        )
        if len(admins) != len(set(ids)):
            raise ValidationException(
                detail="One or more selected users aren't valid, active admins."
            )

        SupportService.assign(ticket, admins, by=request.user)

        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="support_ticket.assigned",
            target=ticket.reporter,
            message=(
                f"{request.user.email} assigned ticket '{ticket.subject}' to "
                f"{', '.join(a.email for a in admins)}"
            ),
        )
        return APIResponse.success(
            data=AdminSupportTicketSerializer(ticket).data, message="Assigned."
        )


@extend_schema(
    tags=["Support"],
    summary="Resolve or dismiss a ticket (assigned Admin, or Super Admin)",
    request=inline_serializer(
        "SupportTicketResolve",
        {
            "resolution": serializers.CharField(required=False, allow_blank=True),
            "dismiss": serializers.BooleanField(required=False),
        },
    ),
    responses={200: OpenApiResponse(description="`data`: the updated ticket.")},
)
class AdminSupportTicketResolveView(APIView):
    def post(self, request, id):
        ticket = _get_ticket_or_404(id)
        if request.user.role != UserRole.SUPERADMIN and not SupportService.can_act_on(
            ticket, request.user
        ):
            raise PermissionDeniedException(detail="This ticket isn't assigned to you.")

        dismiss = bool(request.data.get("dismiss"))
        resolution = (request.data.get("resolution") or "").strip()
        SupportService.resolve(ticket, by=request.user, resolution=resolution, dismiss=dismiss)

        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="support_ticket.resolved" if not dismiss else "support_ticket.dismissed",
            target=ticket.reporter,
            message=f"{request.user.email} {'dismissed' if dismiss else 'resolved'} ticket '{ticket.subject}'",
        )
        return APIResponse.success(
            data=AdminSupportTicketSerializer(ticket).data,
            message="Dismissed." if dismiss else "Resolved.",
        )
