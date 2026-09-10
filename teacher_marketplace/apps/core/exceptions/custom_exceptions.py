"""
Custom exception classes for the Teacher Marketplace Platform.

These exceptions extend DRF's APIException so they integrate
automatically with DRF's exception handling pipeline (status
codes, detail messages), while adding a project-specific
`error_code` attribute that the custom exception handler
(apps/core/exceptions/handlers.py) uses to build a consistent
JSON error response shape across the entire API.

Usage example (inside a service layer or view):
    from apps.core.exceptions.custom_exceptions import ResourceNotFoundException

    raise ResourceNotFoundException(detail="Teacher profile not found.")

Phase 1 note: only generic, reusable exceptions are defined here.
Domain-specific exceptions (e.g. InsufficientTokensException,
LeadAlreadyUnlockedException) belong to later phases once wallet
and lead-matching business logic is introduced - adding them now
would violate the "no business logic in Phase 1" rule.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class BaseAPIException(APIException):
    """
    Root of our custom exception hierarchy. Every custom exception
    in this project should ultimately inherit from this, directly
    or indirectly, so the exception handler can reliably detect
    "our" exceptions vs raw/unexpected ones.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = "An unexpected error occurred. Please try again later."
    default_code = "internal_error"
    error_code = "INTERNAL_ERROR"


class ValidationException(BaseAPIException):
    """
    Raised for request data that fails business-level validation
    rules not already covered by serializer field validation
    (e.g. cross-field checks performed in a service layer).
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The provided data is invalid."
    default_code = "validation_error"
    error_code = "VALIDATION_ERROR"


class ResourceNotFoundException(BaseAPIException):
    """
    Raised when a requested resource (by ID/UUID) does not exist
    or is not visible to the requesting user (e.g. soft-deleted).
    """

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested resource was not found."
    default_code = "not_found"
    error_code = "RESOURCE_NOT_FOUND"


class UnauthorizedException(BaseAPIException):
    """
    Raised when authentication is missing or invalid (distinct
    from PermissionDeniedException: this is "who are you?" rather
    than "you can't do that").
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Authentication credentials were not provided or are invalid."
    default_code = "unauthorized"
    error_code = "UNAUTHORIZED"


class PermissionDeniedException(BaseAPIException):
    """
    Raised when an authenticated user is known, but is not allowed
    to perform the requested action (e.g. a Student calling a
    Teacher-only endpoint).
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You do not have permission to perform this action."
    default_code = "permission_denied"
    error_code = "PERMISSION_DENIED"


class ConflictException(BaseAPIException):
    """
    Raised when a request conflicts with the current state of a
    resource (e.g. attempting to register with an email that
    already exists).
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state of the resource."
    default_code = "conflict"
    error_code = "CONFLICT"


class ThrottledException(BaseAPIException):
    """
    Raised when a client has exceeded the allowed rate of requests.
    Mirrors DRF's built-in Throttled exception but folded into our
    hierarchy so it produces the same response shape as every other
    error in the API.
    """

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Request was throttled. Please try again later."
    default_code = "throttled"
    error_code = "THROTTLED"


class ServiceUnavailableException(BaseAPIException):
    """
    Raised when a downstream dependency (e.g. email provider,
    payment gateway in a later phase) is unavailable. Distinguishes
    infrastructure failures from genuine internal bugs.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The service is temporarily unavailable. Please try again later."
    default_code = "service_unavailable"
    error_code = "SERVICE_UNAVAILABLE"
