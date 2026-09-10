"""
"Connect to Admin" - the student/teacher-facing side.

    GET  /api/v1/support/tickets/   my own tickets (newest first)
    POST /api/v1/support/tickets/   file a new one (multipart, up to 5 screenshots)
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.core.responses import APIResponse
from apps.support.models import ContactPreference, SupportTicket
from apps.support.serializers import SupportTicketSerializer
from apps.support.services import SupportService

MAX_ATTACHMENTS = 5


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


@extend_schema(
    tags=["Support"],
    request=inline_serializer(
        "SupportTicketCreate",
        {
            "subject": serializers.CharField(),
            "description": serializers.CharField(),
            "contact_preference": serializers.ChoiceField(
                choices=ContactPreference.choices, required=False
            ),
            "attachments": serializers.ListField(
                child=serializers.ImageField(), required=False
            ),
        },
    ),
    responses={200: SupportTicketSerializer, 201: SupportTicketSerializer},
)
class MySupportTicketListCreateView(generics.ListCreateAPIView):
    serializer_class = SupportTicketSerializer
    pagination_class = _Pagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportTicket.objects.none()
        return (
            SupportTicket.objects.filter(reporter=self.request.user)
            .prefetch_related("attachments", "assigned_admins")
        )

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

    def create(self, request, *args, **kwargs):
        subject = (request.data.get("subject") or "").strip()
        description = (request.data.get("description") or "").strip()
        if not subject:
            raise ValidationException(detail="Enter a subject.")
        if not description:
            raise ValidationException(detail="Describe the issue.")

        contact_preference = request.data.get("contact_preference") or ContactPreference.NONE
        if contact_preference not in ContactPreference.values:
            raise ValidationException(detail="Invalid contact preference.")

        files = request.FILES.getlist("attachments")
        if len(files) > MAX_ATTACHMENTS:
            raise ValidationException(
                detail=f"Attach at most {MAX_ATTACHMENTS} screenshots."
            )
        try:
            ticket = SupportService.create_ticket(
                request.user,
                subject=subject,
                description=description,
                contact_preference=contact_preference,
                files=files,
            )
        except DjangoValidationError as e:
            raise ValidationException(detail="; ".join(e.messages)) from e

        return APIResponse.success(
            data=SupportTicketSerializer(ticket).data,
            message="Your report has been sent.",
        )
