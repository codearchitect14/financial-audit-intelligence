"""Enumerations shared across the schema.

These are persisted as ``VARCHAR`` with a ``CHECK`` constraint rather than as
native Postgres ``ENUM`` types. Adding a value to a native enum requires
``ALTER TYPE``, which cannot run inside a transactional migration on older
Postgres and complicates rollbacks; a checked varchar has the same integrity
guarantee and evolves with an ordinary constraint swap.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Role assigned to a user within their organization.

    Ordered from most to least privileged. See ``fai.core.permissions`` for the
    hierarchy used by the authorization dependency.
    """

    ADMIN = "admin"
    AUDITOR = "auditor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class FilingType(StrEnum):
    ANNUAL_10K = "10-K"
    QUARTERLY_10Q = "10-Q"
    AMENDED_10KA = "10-K/A"
    AMENDED_10QA = "10-Q/A"
    OTHER = "other"


class FiscalPeriod(StrEnum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    FY = "FY"


class StatementSection(StrEnum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    EQUITY = "equity"
    OTHER = "other"


class FlagSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FlagStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class DetectionMethod(StrEnum):
    """How a flag was produced. No value here involves an LLM by design."""

    RATIO_THRESHOLD = "ratio_threshold"
    ZSCORE_OUTLIER = "zscore_outlier"
    ISOLATION_FOREST = "isolation_forest"
    BENFORD_LAW = "benford_law"
    CLASSIFIER = "classifier"
    ACCOUNTING_IDENTITY = "accounting_identity"
    MANUAL = "manual"


class DocumentType(StrEnum):
    FILING = "filing"
    AUDIT_NOTE = "audit_note"
    POLICY = "policy"
    CONTRACT = "contract"
    OTHER = "other"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class LLMProvider(StrEnum):
    GROQ = "groq"
    GEMINI = "gemini"


class LLMTaskType(StrEnum):
    """Task categories. Each carries its own ``max_tokens`` ceiling."""

    ANOMALY_EXPLANATION = "anomaly_explanation"
    QUESTION_ANSWER = "question_answer"
    REPORT_SECTION = "report_section"


class LLMCallStatus(StrEnum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
