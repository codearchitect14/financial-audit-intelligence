"""Generated audit reports (Phase 6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from fai.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fai.db.models.enums import ReportStatus


class AuditReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A generated report over one statement.

    ``content`` is stored as structured JSON, not rendered prose. The PDF is a
    projection of that structure, which means a report can be re-rendered in a
    new template, or exported in another format, without asking an LLM to write
    anything a second time.
    """

    __tablename__ = "audit_reports"
    __table_args__ = (Index("ix_audit_reports_org_created_at", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("financial_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        SAEnum(ReportStatus, native_enum=False, length=32),
        nullable=False,
        default=ReportStatus.DRAFT,
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Snapshot of the statement risk score at generation time. The live score
    # can move as detectors are retrained; a signed-off report must not.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
