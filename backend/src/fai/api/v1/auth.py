"""Authentication endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, status
from sqlalchemy import select

from fai.api.deps import ClientIp, CurrentUserDep, DbSession, RequireAdmin
from fai.core.errors import ValidationError
from fai.core.rate_limit import limiter
from fai.db.models import User, UserRole
from fai.schemas.auth import (
    LoginRequest,
    OrganizationResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UpdateRoleRequest,
    UserResponse,
)
from fai.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

UserAgent = Annotated[str | None, Header(alias="User-Agent")]


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization and its first user",
)
# Registration is unauthenticated and creates rows, so it is the most attractive
# endpoint for automated abuse. The limit is per client address.
@limiter.limit("5/hour")
async def register(
    request: Request,
    payload: RegisterRequest,
    db: DbSession,
    ip: ClientIp,
    user_agent: UserAgent = None,
) -> RegisterResponse:
    """Register a new organization. The first user becomes its administrator."""
    user, organization, tokens = await auth_service.register(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        user_agent=user_agent,
        ip_address=ip,
    )
    return RegisterResponse(
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(organization),
        tokens=tokens,
    )


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for tokens")
# Tight enough to make online password guessing impractical, loose enough not
# to lock out a person who mistypes a few times.
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: DbSession,
    ip: ClientIp,
    user_agent: UserAgent = None,
) -> TokenResponse:
    """Authenticate and receive an access and refresh token pair."""
    _, tokens = await auth_service.login(
        db,
        email=payload.email,
        password=payload.password,
        user_agent=user_agent,
        ip_address=ip,
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse, summary="Rotate a refresh token")
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    payload: RefreshRequest,
    db: DbSession,
    ip: ClientIp,
    user_agent: UserAgent = None,
) -> TokenResponse:
    """Exchange a refresh token for a new pair.

    Rotation is single-use. Presenting an already-rotated token revokes every
    session for that user, on the assumption that it was stolen.
    """
    return await auth_service.refresh(
        db,
        refresh_token=payload.refresh_token,
        user_agent=user_agent,
        ip_address=ip,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current session",
)
async def logout(
    payload: RefreshRequest,
    db: DbSession,
    current_user: CurrentUserDep,
    ip: ClientIp,
    user_agent: UserAgent = None,
) -> None:
    """Revoke one refresh session. Idempotent."""
    await auth_service.logout(
        db,
        refresh_token=payload.refresh_token,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        ip_address=ip,
        user_agent=user_agent,
    )


@router.get("/me", response_model=UserResponse, summary="Describe the authenticated user")
async def me(db: DbSession, current_user: CurrentUserDep) -> UserResponse:
    user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one()
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}/role",
    response_model=UserResponse,
    summary="Change a member's role",
)
async def update_role(
    user_id: str,
    payload: UpdateRoleRequest,
    db: DbSession,
    current_user: RequireAdmin,
    ip: ClientIp,
) -> UserResponse:
    """Set a role for a member of the caller's own organization."""
    try:
        target_id = uuid.UUID(user_id)
    except ValueError as exc:
        raise ValidationError("user_id must be a UUID.") from exc

    user = await auth_service.set_user_role(
        db,
        actor_id=current_user.id,
        organization_id=current_user.organization_id,
        target_user_id=target_id,
        role=UserRole(payload.role),
        ip_address=ip,
    )
    return UserResponse.model_validate(user)
