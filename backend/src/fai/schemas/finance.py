"""Response models for financial data."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from fai.db.models.enums import (
    DetectionMethod,
    FilingType,
    FiscalPeriod,
    FlagSeverity,
    FlagStatus,
    StatementSection,
)


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    cik: str | None
    ticker: str | None
    sector: str | None
    sic_code: str | None
    country: str | None
    # True for the shared public SEC corpus, which no tenant may edit.
    is_public_reference: bool = False

    @classmethod
    def from_model(cls, company: object) -> Self:
        response = cls.model_validate(company)
        return response.model_copy(
            update={"is_public_reference": getattr(company, "organization_id", None) is None}
        )


class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tag: str
    label: str | None
    # Serialised as a JSON string, not a float. These are exact decimals and
    # IEEE 754 cannot represent them; a JSON number would silently round large
    # values in any client that parses into a double.
    value: Decimal = Field(json_schema_extra={"type": "string"})
    unit: str
    statement_section: StatementSection


class AuditFlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement_id: uuid.UUID
    flag_type: str
    severity: FlagSeverity
    status: FlagStatus
    detection_method: DetectionMethod
    score: float | None
    description: str
    detail: dict[str, Any]
    explanation: str | None
    created_at: datetime


class StatementSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str | None = None
    fiscal_year: int
    fiscal_period: FiscalPeriod
    filing_type: FilingType
    period_end_date: date | None
    filed_date: date | None
    risk_score: float | None
    source_dataset: str

    @classmethod
    def from_model(cls, statement: object) -> Self:
        company = getattr(statement, "company", None)
        response = cls.model_validate(statement)
        if company is not None:
            response = response.model_copy(update={"company_name": company.name})
        return response


class RatioSet(BaseModel):
    """Computed ratios. Each is None when its inputs are missing or zero."""

    current_ratio: float | None = None
    quick_ratio: float | None = None
    debt_to_equity: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    operating_margin: float | None = None
    return_on_assets: float | None = None
    asset_turnover: float | None = None
    accruals_ratio: float | None = None


class StatementDetail(StatementSummary):
    line_items: list[LineItemResponse] = Field(default_factory=list)
    flags: list[AuditFlagResponse] = Field(default_factory=list)
    ratios: RatioSet = Field(default_factory=RatioSet)
    is_fraud_label: bool | None = None


class UpdateFlagRequest(BaseModel):
    status: FlagStatus


class DashboardSummary(BaseModel):
    total_statements: int
    open_flags: int
    critical_flags: int
    high_risk_statements: int
    average_risk_score: float | None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    doc_type: str
    status: str
    chunk_count: int = 0
    created_at: datetime
