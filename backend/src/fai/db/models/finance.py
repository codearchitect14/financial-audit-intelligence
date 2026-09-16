"""Financial reference data: companies, statements, line items, and flags."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fai.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fai.db.models.enums import (
    DetectionMethod,
    FilingType,
    FiscalPeriod,
    FlagSeverity,
    FlagStatus,
    StatementSection,
)


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reporting entity.

    ``organization_id IS NULL`` marks a company from the public SEC corpus,
    shared by every tenant. A non-NULL value marks a private entity that one
    tenant added, which is invisible to the others.
    """

    __tablename__ = "companies"
    __table_args__ = (
        # A CIK identifies a filer globally, so the public corpus must not hold
        # duplicates. Partial index: private rows may reuse a CIK freely.
        Index(
            "uq_companies_public_cik",
            "cik",
            unique=True,
            postgresql_where=text("organization_id IS NULL AND cik IS NOT NULL"),
        ),
        Index("ix_companies_organization_id_name", "organization_id", "name"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    # SEC Central Index Key. Stored as text, not an integer: it is an
    # identifier, is zero-padded to 10 digits in EDGAR URLs, and is never
    # used in arithmetic.
    cik: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sic_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    statements: Mapped[list[FinancialStatement]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )


class FinancialStatement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One filed statement for one company and fiscal period."""

    __tablename__ = "financial_statements"
    __table_args__ = (
        # An accession number uniquely identifies an EDGAR submission.
        # Enforcing uniqueness here is what makes ingestion safely re-runnable.
        UniqueConstraint("company_id", "source_accession", name="uq_statement_accession"),
        Index("ix_statements_company_period", "company_id", "fiscal_year", "fiscal_period"),
        Index("ix_statements_risk_score", "risk_score"),
        CheckConstraint("fiscal_year BETWEEN 1900 AND 2200", name="fiscal_year_range"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="risk_score_range",
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[FiscalPeriod] = mapped_column(
        SAEnum(FiscalPeriod, native_enum=False, length=8), nullable=False
    )
    filing_type: Mapped[FilingType] = mapped_column(
        SAEnum(FilingType, native_enum=False, length=16), nullable=False
    )
    period_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    source_accession: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Phase 3 fraud label, merged from the SEC AAER enforcement releases.
    # NULL means "unlabelled", which is not the same as "not fraud": only a
    # filing inside a matched enforcement window is labelled False.
    is_fraud_label: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    fraud_label_source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Phase 6 aggregate risk score, 0-100, derived from audit_flags.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="statements")
    line_items: Mapped[list[FinancialLineItem]] = relationship(
        back_populates="statement", cascade="all, delete-orphan", passive_deletes=True
    )
    flags: Mapped[list[AuditFlag]] = relationship(
        back_populates="statement", cascade="all, delete-orphan", passive_deletes=True
    )


class FinancialLineItem(UUIDPrimaryKeyMixin, Base):
    """A single tagged value within a statement.

    ``value`` is ``Numeric``, never ``Float``. These figures reach the hundreds
    of billions, are compared for exact accounting identities (assets equals
    liabilities plus equity), and feed Benford digit analysis. Binary floating
    point would introduce drift that silently corrupts all three.
    """

    __tablename__ = "financial_line_items"
    __table_args__ = (
        UniqueConstraint("statement_id", "tag", name="uq_line_item_statement_tag"),
        Index("ix_line_items_tag", "tag"),
    )

    statement_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("financial_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # US-GAAP XBRL tag, for example "Assets" or "NetIncomeLoss".
    tag: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="USD")
    statement_section: Mapped[StatementSection] = mapped_column(
        SAEnum(StatementSection, native_enum=False, length=32),
        nullable=False,
        default=StatementSection.OTHER,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    statement: Mapped[FinancialStatement] = relationship(back_populates="line_items")


class AuditFlag(UUIDPrimaryKeyMixin, Base):
    """A finding raised against a statement by a deterministic detector.

    Nothing in this table is produced by an LLM. The ``explanation`` column is
    filled in later from the cached LLM layer and is purely presentational: the
    finding itself stands without it.
    """

    __tablename__ = "audit_flags"
    __table_args__ = (
        # One detector raises at most one flag of a given type per statement,
        # which is what makes the scoring job idempotent on re-run.
        UniqueConstraint(
            "statement_id",
            "flag_type",
            "detection_method",
            name="uq_flag_statement_type_method",
        ),
        Index("ix_audit_flags_severity_status", "severity", "status"),
    )

    statement_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("financial_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flag_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[FlagSeverity] = mapped_column(
        SAEnum(FlagSeverity, native_enum=False, length=16), nullable=False
    )
    status: Mapped[FlagStatus] = mapped_column(
        SAEnum(FlagStatus, native_enum=False, length=16),
        nullable=False,
        default=FlagStatus.OPEN,
    )
    detection_method: Mapped[DetectionMethod] = mapped_column(
        SAEnum(DetectionMethod, native_enum=False, length=32), nullable=False
    )
    # Detector confidence or magnitude, 0-1. Kept separate from severity, which
    # is the bucketed, human-facing form.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Detector-specific evidence: observed value, expected range, digit
    # distribution. This is what gets sent to the LLM, not the raw dataset.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    statement: Mapped[FinancialStatement] = relationship(back_populates="flags")
