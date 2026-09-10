"""
Exception-handling middleware for the Teacher Marketplace Platform.

Wired up in config/settings/base.py's MIDDLEWARE list as the last
entry, so it wraps everything below it in the middleware stack.

Why this exists in addition to apps/core/exceptions/handlers.py:
    - custom_exception_handler (handlers.py) only runs for
      exceptions raised INSIDE a DRF view's dispatch cycle. It is
      registered via REST_FRAMEWORK["EXCEPTION_HANDLER"] and DRF
      calls it automatically.
    - This middleware is a broader safety net: it catches
      exceptions raised anywhere in the request/response cycle
      that DRF's handler never gets a chance to see - e.g. an
      error raised by another middleware, or (in rare edge cases)
      an exception that escapes DRF's own handling entirely.
    - For requests under /api/, we return the same standard JSON
      error envelope as handlers.py, so API clients never see
      Django's HTML error/debug page regardless of where the
      exception originated.
    - For non-API requests (e.g. /admin/), we deliberately do NOT
      intercept - Django's own admin error handling should behave
      normally.
"""

import logging

from django.http import JsonResponse
from rest_framework import status

logger = logging.getLogger("apps.core.middleware")

API_PATH_PREFIX = "/api/"


class ExceptionHandlingMiddleware:
    """
    Standard Django middleware (new-style, callable-based) that
    wraps the entire request/response cycle in a try/except as a
    final fallback, and implements process_exception as a second
    safety net for exceptions raised specifically during view
    execution that bypass get_response for any reason.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception as exc:  # noqa: BLE001 - intentional catch-all safety net
            return self._handle_exception(request, exc)

    def process_exception(self, request, exception):
        """
        Django calls this hook specifically when a view raises an
        unhandled exception. In normal operation, DRF's own
        exception handling (custom_exception_handler) will have
        already produced a Response before this is ever reached
        for API views. This exists purely as defense-in-depth for
        exceptions that somehow bypass that path.
        """
        if not self._is_api_request(request):
            # Let Django's normal (non-API) error handling proceed
            # untouched, e.g. for /admin/ or any future server-
            # rendered pages.
            return None

        return self._handle_exception(request, exception)

    def _handle_exception(self, request, exc):
        if not self._is_api_request(request):
            # Re-raise so Django's default handling (HTML debug
            # page in DEBUG mode, or the configured 500 template
            # in production) takes over as normal for non-API paths.
            raise exc

        logger.error(
            "Unhandled exception caught by ExceptionHandlingMiddleware "
            "for path %s: %s",
            request.path,
            exc,
            exc_info=True,
            extra={"path": request.path, "method": request.method},
        )

        return JsonResponse(
            {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again later.",
                },
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @staticmethod
    def _is_api_request(request) -> bool:
        return request.path.startswith(API_PATH_PREFIX)
