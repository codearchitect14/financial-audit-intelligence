"""Password hashing and JSON Web Token handling.

Design notes that matter for security review:

* Passwords are hashed with Argon2id, the current recommendation for new
  systems, via passlib. bcrypt is accepted for verification so that a future
  migration from another system does not lock existing users out.
* Access tokens are short lived and stateless; refresh tokens are long lived
  and stateful. Only the refresh token has a server-side record, which is what
  makes a session revocable at all. A stateless-only design cannot log anybody
  out.
* Only a SHA-256 hash of the refresh token is ever stored. A database
  disclosure therefore does not hand an attacker usable sessions.
* Every token carries a ``typ`` claim and it is *verified*. Without that check,
  a refresh token would be accepted as an access token, which quietly converts
  a 30-minute credential into a 7-day one.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from fai.core.config import settings
from fai.core.errors import AuthenticationError

TokenType = Literal["access", "refresh"]

# Argon2id with passlib's defaults, which track the OWASP guidance. bcrypt is
# listed as deprecated-but-verifiable purely for inbound migration.
password_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated=["bcrypt"],
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=4,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return password_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a malformed hash: a corrupted row must
    fail the login, not crash the endpoint.
    """
    try:
        return password_context.verify(password, hashed)
    except ValueError:
        return False


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash uses outdated parameters or an old scheme."""
    return password_context.needs_update(hashed)


def hash_token(token: str) -> str:
    """Hash a refresh token for storage.

    SHA-256 rather than Argon2 deliberately. The token is 256 bits of
    cryptographic randomness, not a low-entropy human secret, so it is not
    subject to dictionary attack and does not need a slow KDF. It is looked up
    on every refresh, where a deliberately slow hash would be a denial-of-
    service vector against ourselves.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    """Generate an opaque refresh token."""
    return secrets.token_urlsafe(48)


@dataclass(frozen=True)
class TokenClaims:
    """Validated claims from an access token."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    token_type: TokenType
    expires_at: datetime
    jti: str


def create_access_token(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Mint a short-lived access token.

    The organization and role are embedded so that ordinary authorization
    decisions need no database round trip. The trade-off is that a role change
    takes effect only at the next refresh, which is why access-token lifetime is
    kept to minutes.
    """
    now = datetime.now(UTC)
    expires = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id),
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> TokenClaims:
    """Verify an access token and return its claims.

    Raises ``AuthenticationError`` for anything that is not a currently valid
    access token. The message is deliberately uniform: telling a caller whether
    a token was expired, forged, or of the wrong type is free reconnaissance.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            # An explicit algorithm list. Accepting the token's own "alg" would
            # permit the classic "alg": "none" forgery.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired credentials") from exc

    if payload.get("typ") != "access":
        # A refresh token presented as an access token. Without this check it
        # would be honoured, turning a 30-minute credential into a 7-day one.
        raise AuthenticationError("Invalid or expired credentials")

    try:
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            organization_id=uuid.UUID(payload["org"]),
            role=str(payload["role"]),
            token_type="access",
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            jti=str(payload.get("jti", "")),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid or expired credentials") from exc


def refresh_token_expiry() -> datetime:
    """Absolute expiry for a newly issued refresh token."""
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
