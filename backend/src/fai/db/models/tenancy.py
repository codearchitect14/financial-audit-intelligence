"""Tenancy, identity, and audit-trail models.

Tenancy rule for the whole schema
---------------------------------
Every tenant-owned table carries an ``organization_id``. On the reference-data
tables (``companies``, ``financial_statements``) the column is **nullable**, and
``NULL`` means "public reference data", which is how the ingested SEC corpus is
stored: one copy, readable by every tenant, writable by none of them. A
non-NULL value means the row is private to that organization.

Every query that returns tenant data must therefore filter on
``organization_id IN (:caller_org, NULL)`` for reference tables and on
``organization_id = :caller_org`` for private tables. That filtering is
centralised in the repository layer rather than repeated in endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fai.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fai.db.models.enums import UserRole

if TYPE_CHECKING:
    from fai.db.models.documents import Document


def role_column() -> Mapped[UserRole]:
    return mapped_column(
        SAEnum(UserRole, native_enum=False, length=32, validate_strings=True),
        nullable=False,
        default=UserRole.VIEWER,
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant. Every user and every piece of private data belongs to one."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    users: Mapped[list["User"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        # The foreign key already declares ON DELETE CASCADE. Without
        # passive_deletes the ORM would instead try to NULL the child FK
        # before deleting the parent, which fails against a NOT NULL
        # column and defeats the database-level guarantee.
        passive_deletes=True,
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated principal, scoped to exactly one organization."""

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_organization_id_role", "organization_id", "role"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Citext would be the stricter choice, but it needs an extension; emails are
    # normalised to lowercase in the service layer before they reach here.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = role_column()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="users")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="uploader")


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """A server-side refresh session, so that a login can be revoked.

    Only a SHA-256 hash of the token is stored. A database disclosure therefore
    does not hand an attacker usable session tokens.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_active(self) -> bool:
        from datetime import UTC

        return self.revoked_at is None and self.expires_at > datetime.now(UTC)


class ActivityLog(UUIDPrimaryKeyMixin, Base):
    """Append-only audit trail of every state-changing action.

    Rows are never updated or deleted by application code. ``user_id`` is
    nullable and uses ``ON DELETE SET NULL`` so that deleting a user cannot
    erase the record of what that user did.
    """

    __tablename__ = "activity_log"
    __table_args__ = (
        Index("ix_activity_log_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_activity_log_resource", "resource_type", "resource_id"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
