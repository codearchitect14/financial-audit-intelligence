"""ORM model registry.

Every model must be imported here. Alembic autogenerate compares the live
database against ``Base.metadata``, and a model that no module imports is
invisible to that comparison, so it would be silently dropped from migrations.
"""

from fai.db.base import Base
from fai.db.models.documents import Document, DocumentChunk
from fai.db.models.enums import (
    DetectionMethod,
    DocumentStatus,
    DocumentType,
    FilingType,
    FiscalPeriod,
    FlagSeverity,
    FlagStatus,
    LLMCallStatus,
    LLMProvider,
    LLMTaskType,
    ReportStatus,
    StatementSection,
    UserRole,
)
from fai.db.models.finance import (
    AuditFlag,
    Company,
    FinancialLineItem,
    FinancialStatement,
)
from fai.db.models.llm import LLMResponseCache, LLMUsageLog
from fai.db.models.reports import AuditReport
from fai.db.models.tenancy import ActivityLog, Organization, RefreshToken, User

__all__ = [
    "ActivityLog",
    "AuditFlag",
    "AuditReport",
    "Base",
    "Company",
    "DetectionMethod",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "DocumentType",
    "FilingType",
    "FinancialLineItem",
    "FinancialStatement",
    "FiscalPeriod",
    "FlagSeverity",
    "FlagStatus",
    "LLMCallStatus",
    "LLMProvider",
    "LLMResponseCache",
    "LLMTaskType",
    "LLMUsageLog",
    "Organization",
    "RefreshToken",
    "ReportStatus",
    "StatementSection",
    "User",
    "UserRole",
]
