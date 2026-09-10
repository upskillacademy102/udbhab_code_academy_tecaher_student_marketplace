"""
Standard API response helper for the Teacher Marketplace Platform.

Pairs with the error envelope produced by:
    - apps/core/exceptions/handlers.py (custom_exception_handler)
    - apps/core/middleware/exception_middleware.py

Together these guarantee EVERY response from /api/v1/... - success
or failure - has one of exactly two top-level shapes:

    Success:
        {
            "success": true,
            "message": "Optional human-readable message",
            "data": { ... } | [ ... ] | null
        }

    Error (see handlers.py for details):
        {
            "success": false,
            "error": {
                "code": "...",
                "message": "...",
                "details": { ... }  # optional
            }
        }

Usage inside a view:
    from apps.core.responses import APIResponse

    class TeacherListView(APIView):
        def get(self, request):
            teachers = [...]
            serializer = TeacherSerializer(teachers, many=True)
            return APIResponse.success(data=serializer.data)
"""

from rest_framework import status
from rest_framework.response import Response


class APIResponse:
    """
    Thin factory for building consistently-shaped success
    responses. Intentionally NOT a Response subclass - it's a
    collection of static constructors that return plain DRF
    Response objects, which keeps usage in views simple
    (`return APIResponse.success(...)`) without altering how
    DRF's rendering/content-negotiation pipeline treats the
    response.
    """

    @staticmethod
    def success(
        data=None, message: str = None, http_status=status.HTTP_200_OK, **extra
    ):
        """
        Standard success envelope.

        Args:
            data: The primary payload - a dict, list, serializer
                .data, or None for responses with no body content
                (e.g. a successful DELETE).
            message: Optional human-readable success message
                (e.g. "Password updated successfully.").
            http_status: HTTP status code, defaults to 200 OK.
            **extra: Additional top-level keys to merge into the
                envelope (e.g. pagination metadata), used sparingly
                to keep the envelope shape predictable.
        """
        payload = {
            "success": True,
            "data": data,
        }
        if message is not None:
            payload["message"] = message
        if extra:
            payload.update(extra)

        return Response(payload, status=http_status)

    @staticmethod
    def created(data=None, message: str = "Resource created successfully."):
        """Convenience wrapper for 201 Created responses."""
        return APIResponse.success(
            data=data, message=message, http_status=status.HTTP_201_CREATED
        )

    @staticmethod
    def no_content(message: str = None):
        """
        Convenience wrapper for 204 No Content responses (e.g. a
        successful DELETE or Logout). Per HTTP spec, a 204 response
        must have an empty body, so this deliberately ignores
        `data` and ships no JSON body when message is None.
        """
        if message is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        # Some clients prefer a small confirmation body even on
        # delete-style actions; use 200 instead of 204 in that case
        # since 204 responses must not include a body.
        return APIResponse.success(
            data=None, message=message, http_status=status.HTTP_200_OK
        )

    @staticmethod
    def paginated(data, pagination_meta: dict, message: str = None):
        """
        Success envelope for paginated list responses. Keeps
        pagination metadata (count, next, previous, etc.) alongside
        `data` rather than nesting it, so clients access
        `response.data.count` directly rather than digging into a
        nested pagination object.

        Args:
            data: The list of serialized items for the current page.
            pagination_meta: Dict typically produced by DRF's
                paginator (e.g. {"count": 50, "next": "...",
                "previous": None}).
        """
        return APIResponse.success(
            data=data,
            message=message,
            **pagination_meta,
        )
