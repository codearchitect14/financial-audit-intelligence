"""Authentication service.

Holds the registration, login, refresh, and logout flows. Kept out of the
router so the rules can be tested without going through HTTP, and so the
endpoints stay thin enough to read in one screen.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.config import settings
from fai.core.errors import AuthenticationError, ConflictError, NotFoundError
from fai.core.logging import get_logger
from fai.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    refresh_token_expiry,
    verify_password,
)
from fai.db.models import Organization, RefreshToken, User, UserRole
from fai.schemas.auth import TokenResponse
from fai.services import activity

log = get_logger(__name__)

# A dummy Argon2 hash of a random value, used to equalise the cost of a login
# attempt against an address that does not exist. Without it, "no such user"
# returns in microseconds while a real user costs a full Argon2 verification,
# and the difference is a reliable account-enumeration oracle.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder-value")


def slugify(name: str) -> str:
    """Turn an organization name into a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:48] or "org"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    """Find a free slug, appending a short suffix on collision."""
    candidate = base
    for _ in range(5):
        exists = (
            await db.execute(select(Organization.id).where(Organization.slug == candidate))
        ).first()
        if exists is None:
            return candidate
        candidate = f"{base[:40]}-{uuid.uuid4().hex[:6]}"
    raise ConflictError("Could not allocate an organization slug; try a different name.")


async def _issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    """Mint an access/refresh pair and persist the refresh session."""
    refresh_value = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_value),
            expires_at=refresh_token_expiry(),
            user_agent=user_agent[:512] if user_agent else None,
            ip_address=ip_address,
        )
    )

    access = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh_value,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def register(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    organization_name: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, Organization, TokenResponse]:
    """Create an organization and its first user.

    The first user of a new organization is its admin: somebody has to be able
    to invite the others, and an organization with no administrator is
    unusable.
    """
    existing = (await db.execute(select(User.id).where(User.email == email))).first()
    if existing is not None:
        raise ConflictError("An account with that email address already exists.")

    organization = Organization(
        name=organization_name.strip(),
        slug=await _unique_slug(db, slugify(organization_name)),
    )
    db.add(organization)
    await db.flush()

    user = User(
        organization_id=organization.id,
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)

    try:
        await db.flush()
    except IntegrityError as exc:
        # Two simultaneous registrations for the same address: the unique index
        # is the real arbiter, the pre-check above is only a courtesy.
        await db.rollback()
        raise ConflictError("An account with that email address already exists.") from exc

    tokens = await _issue_tokens(db, user, user_agent=user_agent, ip_address=ip_address)

    await activity.record(
        db,
        action=activity.ACTION_USER_REGISTERED,
        resource_type="user",
        resource_id=user.id,
        organization_id=organization.id,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(user)
    await db.refresh(organization)

    log.info("user_registered", user_id=str(user.id), organization_id=str(organization.id))
    return user, organization, tokens


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, TokenResponse]:
    """Authenticate a user and issue tokens."""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    # Always run a verification, even with no user, so that the response time
    # does not reveal whether the address is registered.
    stored_hash = user.hashed_password if user is not None else _DUMMY_HASH
    password_ok = verify_password(password, stored_hash)

    if user is None or not password_ok or not user.is_active:
        await activity.record(
            db,
            action=activity.ACTION_USER_LOGIN_FAILED,
            resource_type="user",
            resource_id=user.id if user else None,
            organization_id=user.organization_id if user else None,
            # The address is recorded for forensics; the password never is.
            detail={"email": email},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
        # One message for every failure mode. Distinguishing "no such user"
        # from "wrong password" hands an attacker a list of valid accounts.
        raise AuthenticationError("Incorrect email or password.")

    # Opportunistic upgrade when the stored hash predates current parameters.
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)

    user.last_login_at = datetime.now(UTC)
    tokens = await _issue_tokens(db, user, user_agent=user_agent, ip_address=ip_address)

    await activity.record(
        db,
        action=activity.ACTION_USER_LOGIN,
        resource_type="user",
        resource_id=user.id,
        organization_id=user.organization_id,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(user)

    log.info("user_logged_in", user_id=str(user.id))
    return user, tokens


async def refresh(
    db: AsyncSession,
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    """Exchange a refresh token for a new pair, rotating the old one.

    Rotation is single-use: presenting a token that has already been rotated
    means either a replay or a stolen token, and the whole session family is
    revoked rather than silently re-issued.
    """
    token_hash = hash_token(refresh_token)
    record = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()

    if record is None:
        raise AuthenticationError("Invalid or expired refresh token.")

    if record.revoked_at is not None:
        # A revoked token presented again is the classic signal of theft: the
        # legitimate client already rotated it, so somebody else has a copy.
        # Revoke every live session for the user and force a fresh login.
        await _revoke_all_for_user(db, record.user_id)
        await activity.record(
            db,
            action=activity.ACTION_TOKEN_REUSE_DETECTED,
            resource_type="refresh_token",
            resource_id=record.id,
            user_id=record.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
        log.warning("refresh_token_reuse_detected", user_id=str(record.user_id))
        raise AuthenticationError("Invalid or expired refresh token.")

    if record.expires_at <= datetime.now(UTC):
        raise AuthenticationError("Invalid or expired refresh token.")

    user = (await db.execute(select(User).where(User.id == record.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid or expired refresh token.")

    record.revoked_at = datetime.now(UTC)
    tokens = await _issue_tokens(db, user, user_agent=user_agent, ip_address=ip_address)

    await activity.record(
        db,
        action=activity.ACTION_TOKEN_REFRESHED,
        resource_type="refresh_token",
        resource_id=record.id,
        organization_id=user.organization_id,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return tokens


async def _revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke every live refresh session for a user."""
    now = datetime.now(UTC)
    tokens = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).scalars()
    count = 0
    for token in tokens:
        token.revoked_at = now
        count += 1
    return count


async def logout(
    db: AsyncSession,
    *,
    refresh_token: str,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Revoke one session.

    Revoking an already-revoked or unknown token is not an error: logout must
    be idempotent, and reporting "that token does not exist" would leak whether
    a guessed token was ever valid.
    """
    record = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(refresh_token),
                RefreshToken.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)

    await activity.record(
        db,
        action=activity.ACTION_USER_LOGOUT,
        resource_type="user",
        resource_id=user_id,
        organization_id=organization_id,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()


async def set_user_role(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    organization_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role: UserRole,
    ip_address: str | None = None,
) -> User:
    """Change a member's role within the caller's organization."""
    target = (
        await db.execute(
            select(User).where(
                User.id == target_user_id,
                # Scoped to the caller's organization: an admin of one tenant
                # must not be able to re-role a member of another.
                User.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()

    if target is None:
        raise NotFoundError("No such member of this organization.")

    if target.id == actor_id and role is not UserRole.ADMIN:
        # Preventing self-demotion avoids the state where an organization has
        # no administrator and nobody can create one.
        raise ConflictError("You cannot remove your own admin role.")

    previous = target.role
    target.role = role

    await activity.record(
        db,
        action=activity.ACTION_USER_ROLE_CHANGED,
        resource_type="user",
        resource_id=target.id,
        organization_id=organization_id,
        user_id=actor_id,
        detail={"from": previous.value, "to": role.value},
        ip_address=ip_address,
    )
    await db.commit()
    await db.refresh(target)
    return target
