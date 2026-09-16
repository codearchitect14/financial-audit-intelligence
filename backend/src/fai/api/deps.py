"""Shared FastAPI dependencies.

The important object here is ``CurrentUser``. Every authenticated endpoint
receives one, and every tenant-scoped query derives its filter from
``current_user.organization_id`` rather than from anything in the request body
or path. That is the single rule that prevents cross-tenant access: a caller
can ask for another organization's resource id, but the query will not match it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.config import settings
from fai.core.errors import AuthenticationError, PermissionDeniedError
from fai.core.permissions import CAPABILITY_MINIMUM, can, has_at_least
from fai.core.security import decode_access_token
from fai.db.models import User, UserRole
from fai.db.session import get_db

# auto_error=False so that a missing header raises our own AuthenticationError
# with the standard envelope, rather than FastAPI's differently-shaped 401.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/auth/login",
    auto_error=False,
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller, resolved once per request."""

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    role: UserRole

    def require(self, capability: str) -> None:
        """Raise unless this user holds a capability."""
        if not can(self.role, capability):
            raise PermissionDeniedError(
                f"This action requires the "
                f"{CAPABILITY_MINIMUM.get(capability, UserRole.ADMIN).value} role or higher."
            )


async def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> CurrentUser:
    """Resolve the bearer token to an active user.

    The token carries the role, but the user is still loaded from the database
    on every request. That costs one indexed primary-key lookup and is what
    makes deactivating an account take effect immediately rather than whenever
    the current access token happens to expire.
    """
    if not token:
        raise AuthenticationError("Authentication required")

    claims = decode_access_token(token)

    user = (await db.execute(select(User).where(User.id == claims.user_id))).scalar_one_or_none()

    if user is None or not user.is_active:
        raise AuthenticationError("Authentication required")

    # A user moved between organizations invalidates tokens minted for the old
    # one. Trusting the token's org claim here would leave a window in which a
    # departed member still reads their former tenant's data.
    if user.organization_id != claims.organization_id:
        raise AuthenticationError("Authentication required")

    return CurrentUser(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(minimum: UserRole) -> Callable[[CurrentUser], CurrentUser]:
    """Build a dependency enforcing a minimum role."""

    def dependency(current_user: CurrentUserDep) -> CurrentUser:
        if not has_at_least(current_user.role, minimum):
            raise PermissionDeniedError(f"This action requires the {minimum.value} role or higher.")
        return current_user

    return dependency


def require_capability(capability: str) -> Callable[[CurrentUser], CurrentUser]:
    """Build a dependency enforcing a named capability."""

    def dependency(current_user: CurrentUserDep) -> CurrentUser:
        current_user.require(capability)
        return current_user

    return dependency


RequireAdmin = Annotated[CurrentUser, Depends(require_role(UserRole.ADMIN))]
RequireAuditor = Annotated[CurrentUser, Depends(require_role(UserRole.AUDITOR))]
RequireReviewer = Annotated[CurrentUser, Depends(require_role(UserRole.REVIEWER))]


def client_ip(request: Request) -> str | None:
    """Best-effort client address for the audit log.

    ``X-Forwarded-For`` is trusted only for its first entry and only because the
    application is expected to sit behind exactly one managed proxy. This value
    is recorded for forensics; it is never used for an authorization decision,
    because a header a client controls cannot carry one.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


ClientIp = Annotated[str | None, Depends(client_ip)]


def get_upload_root() -> Path:
    """Root directory for stored uploads.

    A dependency rather than a direct settings read so that tests can point it
    at a temporary directory through ``app.dependency_overrides``. Settings are
    frozen by design and must not be mutated at runtime.
    """
    return Path(settings.upload_dir)


UploadRoot = Annotated[Path, Depends(get_upload_root)]
