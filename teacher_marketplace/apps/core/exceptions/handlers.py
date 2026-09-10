"""
Custom DRF exception handler for the Teacher Marketplace Platform.

Wired up in config/settings/base.py via:
    REST_FRAMEWORK["EXCEPTION_HANDLER"] = (
        "apps.core.exceptions.handlers.custom_exception_handler"
    )

Goal: every error response returned by the API - regardless of
whether it came from one of our custom exceptions (see
custom_exceptions.py), a built-in DRF/Django exception, or an
unhandled bug - has the exact same JSON shape:

    {
        "success": false,
        "error": {
            "code": "RESOURCE_NOT_FOUND",
            "message": "The requested resource was not found.",
            "details": { ... optional field-level errors ... }
        }
    }

This lets frontend/mobile clients write one generic error-handling
code path instead of branching per endpoint.
"""

import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_exception_handler

from apps.core.exceptions.custom_exceptions import BaseAPIException

logger = logging.getLogger("apps.core.exceptions")


def _build_error_response(code: str, message: str, details=None, http_status=None):
    """
    Assembles the standard error envelope used across the whole API.
    `details` is optional and typically holds field-level validation
    errors (e.g. {"email": ["This field is required."]}).
    """
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details is not None:
        payload["error"]["details"] = details

    return Response(payload, status=http_status)


def custom_exception_handler(exc, context):
    """
    Entry point DRF calls whenever a view raises an exception.

    Flow:
        1. Let DRF's default handler run first - it already knows
           how to turn most built-in exceptions (ValidationError,
           NotAuthenticated, PermissionDenied, Throttled, Http404,
           etc.) into a Response with the correct status code.
        2. If DRF produced a response, re-wrap its payload into our
           standard envelope, pulling an `error_code` off the
           exception if it's one of ours (BaseAPIException), or
           deriving a generic one from the exception class name.
        3. If DRF's handler returned None (meaning it doesn't know
           how to handle this exception - i.e. it's an unexpected,
           unhandled error), log the full exception and return a
           generic 500 response, never leaking internal details or
           stack traces to the client.
    """
    # Normalize a couple of common non-DRF exceptions into DRF's
    # equivalents so the default handler can process them uniformly.
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = drf_default_exception_handler(exc, context)

    if response is not None:
        # Determine the error code.
        if isinstance(exc, BaseAPIException):
            code = exc.error_code
        else:
            # Fall back to a readable code derived from built-in DRF
            # exceptions, e.g. NotAuthenticated -> "NOT_AUTHENTICATED".
            code = _derive_code_from_exception_class(exc)

        # Determine the human-readable message and optional details.
        message, details = _extract_message_and_details(response.data)

        return _build_error_response(
            code=code,
            message=message,
            details=details,
            http_status=response.status_code,
        )

    # ------------------------------------------------------------
    # Unhandled / unexpected exception: DRF's default handler
    # returned None, meaning this isn't a recognized API exception
    # at all (e.g. a bug raising a bare ValueError, a database
    # error, etc.). Log it with full traceback for debugging, and
    # return a generic, safe 500 to the client.
    # ------------------------------------------------------------
    request = context.get("request")
    logger.error(
        "Unhandled exception in view %s: %s",
        context.get("view"),
        exc,
        exc_info=True,
        extra={
            "path": getattr(request, "path", None),
            "method": getattr(request, "method", None),
        },
    )

    return _build_error_response(
        code="INTERNAL_ERROR",
        message="An unexpected error occurred. Please try again later.",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _derive_code_from_exception_class(exc) -> str:
    """
    Builds a SCREAMING_SNAKE_CASE error code from a DRF exception's
    class name for exceptions that aren't one of our own
    BaseAPIException subclasses, e.g.:
        NotAuthenticated -> "NOT_AUTHENTICATED"
        Throttled        -> "THROTTLED"
        ValidationError  -> "VALIDATION_ERROR"
    """
    name = exc.__class__.__name__
    snake = "".join(
        f"_{char}" if char.isupper() and i != 0 else char for i, char in enumerate(name)
    ).upper()
    return snake.lstrip("_")


def _extract_message_and_details(response_data):
    """
    DRF's default error payloads come in a few different shapes
    depending on the exception type:

        - Simple:            {"detail": "Not found."}
        - Field validation:   {"email": ["This field is required."]}
        - Non-field errors:   {"non_field_errors": ["..."]}

    This normalizes all of them into a single top-level `message`
    string plus an optional `details` dict, so the envelope shape
    is always predictable for clients.
    """
    if isinstance(response_data, dict) and "detail" in response_data:
        return str(response_data["detail"]), None

    if isinstance(response_data, dict):
        # Field-level validation errors - use a generic top-level
        # message and preserve the field breakdown in `details`.
        message = "One or more fields failed validation."
        return message, response_data

    if isinstance(response_data, list):
        # Rare, but some DRF exceptions return a bare list of errors.
        message = " ".join(str(item) for item in response_data)
        return message, None

    return str(response_data), None
