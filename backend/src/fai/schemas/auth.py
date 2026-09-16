"""Request and response models for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from fai.db.models.enums import UserRole

# Long enough to resist offline attack, short enough to stay usable. Length is
# the only password rule enforced: composition rules ("one symbol, one digit")
# measurably reduce entropy by pushing people toward predictable patterns, and
# current NIST guidance advises against them.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str = Field(min_length=1, max_length=255)
    organization_name: str = Field(min_length=1, max_length=255)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        """Lowercase at the boundary.

        The uniqueness constraint is a plain unique index, so two addresses
        differing only in case would otherwise both be registerable and the
        second would be unable to log in predictably.
        """
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    organization_id: uuid.UUID
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class RegisterResponse(BaseModel):
    user: UserResponse
    organization: OrganizationResponse
    tokens: TokenResponse


class UpdateRoleRequest(BaseModel):
    role: UserRole
