"""Initial schema.

Creates the full table set plus the two extensions the schema depends on.

Revision ID: 0001
Revises:
Create Date: 2026-09-16 06:14:22.534557
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions are created here, not only in the container init script.
    # A managed provider (Neon, Supabase) never runs that script, so without
    # this the first deployment would fail on the vector column below.
    # Both statements are idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "llm_response_cache",
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum(
                "ANOMALY_EXPLANATION",
                "QUESTION_ANSWER",
                "REPORT_SECTION",
                name="llmtasktype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("GROQ", "GEMINI", name="llmprovider", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_response_cache")),
        sa.UniqueConstraint("prompt_hash", "task_type", "model", name="uq_llm_cache_key"),
    )
    op.create_index(
        op.f("ix_llm_response_cache_created_at"), "llm_response_cache", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_llm_response_cache_prompt_hash"),
        "llm_response_cache",
        ["prompt_hash"],
        unique=False,
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_index(
        op.f("ix_organizations_created_at"), "organizations", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_organizations_slug"), "organizations", ["slug"], unique=True)
    op.create_table(
        "companies",
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=True),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("sic_code", sa.String(length=8), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_companies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
    )
    op.create_index(op.f("ix_companies_cik"), "companies", ["cik"], unique=False)
    op.create_index(op.f("ix_companies_created_at"), "companies", ["created_at"], unique=False)
    op.create_index(
        "ix_companies_organization_id_name", "companies", ["organization_id", "name"], unique=False
    )
    op.create_index(op.f("ix_companies_sic_code"), "companies", ["sic_code"], unique=False)
    op.create_index(op.f("ix_companies_ticker"), "companies", ["ticker"], unique=False)
    op.create_index(
        "uq_companies_public_cik",
        "companies",
        ["cik"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL AND cik IS NOT NULL"),
    )
    op.create_table(
        "llm_usage_log",
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column(
            "provider",
            sa.Enum("GROQ", "GEMINI", name="llmprovider", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum(
                "ANOMALY_EXPLANATION",
                "QUESTION_ANSWER",
                "REPORT_SECTION",
                name="llmtasktype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCESS",
                "RATE_LIMITED",
                "ERROR",
                name="llmcallstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("was_fallback", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_llm_usage_log_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usage_log")),
    )
    op.create_index(
        op.f("ix_llm_usage_log_created_at"), "llm_usage_log", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_llm_usage_log_prompt_hash"), "llm_usage_log", ["prompt_hash"], unique=False
    )
    op.create_index(
        "ix_llm_usage_org_created_at",
        "llm_usage_log",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_usage_provider_created_at",
        "llm_usage_log",
        ["provider", "created_at"],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "ADMIN",
                "AUDITOR",
                "REVIEWER",
                "VIEWER",
                name="userrole",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_users_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"], unique=False)
    op.create_index(
        "ix_users_organization_id_role", "users", ["organization_id", "role"], unique=False
    )
    op.create_table(
        "activity_log",
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_activity_log_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_activity_log_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_log")),
    )
    op.create_index(op.f("ix_activity_log_action"), "activity_log", ["action"], unique=False)
    op.create_index(
        op.f("ix_activity_log_created_at"), "activity_log", ["created_at"], unique=False
    )
    op.create_index(
        "ix_activity_log_organization_id_created_at",
        "activity_log",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_activity_log_resource", "activity_log", ["resource_type", "resource_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "doc_type",
            sa.Enum(
                "FILING",
                "AUDIT_NOTE",
                "POLICY",
                "CONTRACT",
                "OTHER",
                name="documenttype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED",
                "CHUNKING",
                "EMBEDDING",
                "INDEXED",
                "FAILED",
                name="documentstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_documents_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_documents_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("organization_id", "sha256", name="uq_document_org_sha256"),
    )
    op.create_index(op.f("ix_documents_created_at"), "documents", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_documents_organization_id"), "documents", ["organization_id"], unique=False
    )
    op.create_index(
        "ix_documents_organization_id_status",
        "documents",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=False)
    op.create_table(
        "financial_statements",
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column(
            "fiscal_period",
            sa.Enum("Q1", "Q2", "Q3", "Q4", "FY", name="fiscalperiod", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column(
            "filing_type",
            sa.Enum(
                "ANNUAL_10K",
                "QUARTERLY_10Q",
                "AMENDED_10KA",
                "AMENDED_10QA",
                "OTHER",
                name="filingtype",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=True),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column("source_accession", sa.String(length=32), nullable=True),
        sa.Column("is_fraud_label", sa.Boolean(), nullable=True),
        sa.Column("fraud_label_source", sa.String(length=64), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("risk_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fiscal_year BETWEEN 1900 AND 2200",
            name=op.f("ck_financial_statements_fiscal_year_range"),
        ),
        sa.CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name=op.f("ck_financial_statements_risk_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_financial_statements_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_financial_statements_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_statements")),
        sa.UniqueConstraint("company_id", "source_accession", name="uq_statement_accession"),
    )
    op.create_index(
        op.f("ix_financial_statements_company_id"),
        "financial_statements",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_financial_statements_created_at"),
        "financial_statements",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_financial_statements_is_fraud_label"),
        "financial_statements",
        ["is_fraud_label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_financial_statements_organization_id"),
        "financial_statements",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_statements_company_period",
        "financial_statements",
        ["company_id", "fiscal_year", "fiscal_period"],
        unique=False,
    )
    op.create_index(
        "ix_statements_risk_score", "financial_statements", ["risk_score"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_index(
        "ix_refresh_tokens_user_id_revoked_at",
        "refresh_tokens",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "audit_flags",
        sa.Column("statement_id", sa.UUID(), nullable=False),
        sa.Column("flag_type", sa.String(length=64), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "INFO",
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
                name="flagseverity",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "ACKNOWLEDGED",
                "RESOLVED",
                "DISMISSED",
                name="flagstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "detection_method",
            sa.Enum(
                "RATIO_THRESHOLD",
                "ZSCORE_OUTLIER",
                "ISOLATION_FOREST",
                "BENFORD_LAW",
                "CLASSIFIER",
                "ACCOUNTING_IDENTITY",
                "MANUAL",
                name="detectionmethod",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("explained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["financial_statements.id"],
            name=op.f("fk_audit_flags_statement_id_financial_statements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_flags")),
        sa.UniqueConstraint(
            "statement_id", "flag_type", "detection_method", name="uq_flag_statement_type_method"
        ),
    )
    op.create_index(op.f("ix_audit_flags_created_at"), "audit_flags", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_flags_flag_type"), "audit_flags", ["flag_type"], unique=False)
    op.create_index(
        "ix_audit_flags_severity_status", "audit_flags", ["severity", "status"], unique=False
    )
    op.create_index(
        op.f("ix_audit_flags_statement_id"), "audit_flags", ["statement_id"], unique=False
    )
    op.create_table(
        "audit_reports",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("statement_id", sa.UUID(), nullable=False),
        sa.Column("generated_by", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "GENERATING",
                "COMPLETE",
                "FAILED",
                name="reportstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "content", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("pdf_path", sa.String(length=1024), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["generated_by"],
            ["users.id"],
            name=op.f("fk_audit_reports_generated_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_reports_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["financial_statements.id"],
            name=op.f("fk_audit_reports_statement_id_financial_statements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_reports")),
    )
    op.create_index(
        op.f("ix_audit_reports_created_at"), "audit_reports", ["created_at"], unique=False
    )
    op.create_index(
        "ix_audit_reports_org_created_at",
        "audit_reports",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_reports_organization_id"), "audit_reports", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_reports_statement_id"), "audit_reports", ["statement_id"], unique=False
    )
    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=384), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_document_chunks_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_chunks_organization_id"),
        "document_chunks",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "financial_line_items",
        sa.Column("statement_id", sa.UUID(), nullable=False),
        sa.Column("tag", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=True),
        sa.Column("value", sa.Numeric(precision=28, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column(
            "statement_section",
            sa.Enum(
                "BALANCE_SHEET",
                "INCOME_STATEMENT",
                "CASH_FLOW",
                "EQUITY",
                "OTHER",
                name="statementsection",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["financial_statements.id"],
            name=op.f("fk_financial_line_items_statement_id_financial_statements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_line_items")),
        sa.UniqueConstraint("statement_id", "tag", name="uq_line_item_statement_tag"),
    )
    op.create_index(
        op.f("ix_financial_line_items_statement_id"),
        "financial_line_items",
        ["statement_id"],
        unique=False,
    )
    op.create_index("ix_line_items_tag", "financial_line_items", ["tag"], unique=False)


def downgrade() -> None:
    # The extensions are deliberately not dropped. They may be shared with
    # other schemas in the same database, and dropping the vector type would
    # cascade into any object depending on it.
    op.drop_index("ix_line_items_tag", table_name="financial_line_items")
    op.drop_index(op.f("ix_financial_line_items_statement_id"), table_name="financial_line_items")
    op.drop_table("financial_line_items")
    op.drop_index(op.f("ix_document_chunks_organization_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_audit_reports_statement_id"), table_name="audit_reports")
    op.drop_index(op.f("ix_audit_reports_organization_id"), table_name="audit_reports")
    op.drop_index("ix_audit_reports_org_created_at", table_name="audit_reports")
    op.drop_index(op.f("ix_audit_reports_created_at"), table_name="audit_reports")
    op.drop_table("audit_reports")
    op.drop_index(op.f("ix_audit_flags_statement_id"), table_name="audit_flags")
    op.drop_index("ix_audit_flags_severity_status", table_name="audit_flags")
    op.drop_index(op.f("ix_audit_flags_flag_type"), table_name="audit_flags")
    op.drop_index(op.f("ix_audit_flags_created_at"), table_name="audit_flags")
    op.drop_table("audit_flags")
    op.drop_index("ix_refresh_tokens_user_id_revoked_at", table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_statements_risk_score", table_name="financial_statements")
    op.drop_index("ix_statements_company_period", table_name="financial_statements")
    op.drop_index(
        op.f("ix_financial_statements_organization_id"), table_name="financial_statements"
    )
    op.drop_index(op.f("ix_financial_statements_is_fraud_label"), table_name="financial_statements")
    op.drop_index(op.f("ix_financial_statements_created_at"), table_name="financial_statements")
    op.drop_index(op.f("ix_financial_statements_company_id"), table_name="financial_statements")
    op.drop_table("financial_statements")
    op.drop_index(op.f("ix_documents_sha256"), table_name="documents")
    op.drop_index("ix_documents_organization_id_status", table_name="documents")
    op.drop_index(op.f("ix_documents_organization_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_created_at"), table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_activity_log_resource", table_name="activity_log")
    op.drop_index("ix_activity_log_organization_id_created_at", table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_created_at"), table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_action"), table_name="activity_log")
    op.drop_table("activity_log")
    op.drop_index("ix_users_organization_id_role", table_name="users")
    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_created_at"), table_name="users")
    op.drop_table("users")
    op.drop_index("ix_llm_usage_provider_created_at", table_name="llm_usage_log")
    op.drop_index("ix_llm_usage_org_created_at", table_name="llm_usage_log")
    op.drop_index(op.f("ix_llm_usage_log_prompt_hash"), table_name="llm_usage_log")
    op.drop_index(op.f("ix_llm_usage_log_created_at"), table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
    op.drop_index(
        "uq_companies_public_cik",
        table_name="companies",
        postgresql_where=sa.text("organization_id IS NULL AND cik IS NOT NULL"),
    )
    op.drop_index(op.f("ix_companies_ticker"), table_name="companies")
    op.drop_index(op.f("ix_companies_sic_code"), table_name="companies")
    op.drop_index("ix_companies_organization_id_name", table_name="companies")
    op.drop_index(op.f("ix_companies_created_at"), table_name="companies")
    op.drop_index(op.f("ix_companies_cik"), table_name="companies")
    op.drop_table("companies")
    op.drop_index(op.f("ix_organizations_slug"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_created_at"), table_name="organizations")
    op.drop_table("organizations")
    op.drop_index(op.f("ix_llm_response_cache_prompt_hash"), table_name="llm_response_cache")
    op.drop_index(op.f("ix_llm_response_cache_created_at"), table_name="llm_response_cache")
    op.drop_table("llm_response_cache")
