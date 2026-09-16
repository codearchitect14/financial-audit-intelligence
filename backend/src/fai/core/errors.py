"""Application error types and their HTTP representation.

Every error the API returns deliberately passes through one of these classes so
that responses share a single JSON shape and so that internal details are never
leaked to a client by accident.
"""

from __future__ import annotations

from typing import Any

from fastapi import status


class AppError(Exception):
    """Base class for every expected, client-facing failure.

    ``message`` is safe to show to a caller. Anything sensitive belongs in the
    log record, not in ``message`` or ``details``.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None):
        self.message = message or self.__class__.__doc__ or "Unexpected error"
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            payload["error"]["details"] = self.details
        return payload


class NotFoundError(AppError):
    """The requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    """The request conflicts with the current state of the resource."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationError(AppError):
    """The request was well formed but semantically invalid."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"


class AuthenticationError(AppError):
    """Authentication credentials were missing or invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"


class PermissionDeniedError(AppError):
    """The authenticated user may not perform this action."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class RateLimitedError(AppError):
    """Too many requests. Retry later."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class UpstreamError(AppError):
    """A dependency the request relies on is unavailable."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"
