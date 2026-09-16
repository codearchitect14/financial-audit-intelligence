"""Company, statement, and flag endpoints.

Every handler resolves resources through ``fai.repositories.finance``, which
applies the tenant filter. A resource belonging to another organization does not
resolve, so it returns 404 rather than 403: telling a caller that an id exists
but is not theirs confirms the existence of another tenant's data.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from fai.api.deps import ClientIp, CurrentUserDep, DbSession
from fai.core.errors import NotFoundError
from fai.db.models.enums import FlagSeverity, FlagStatus
from fai.detection.ratios import compute_ratios
from fai.repositories import finance as repo
from fai.schemas.common import Page, PageParams
from fai.schemas.finance import (
    AuditFlagResponse,
    CompanyResponse,
    DashboardSummary,
    LineItemResponse,
    RatioSet,
    StatementDetail,
    StatementSummary,
    UpdateFlagRequest,
)
from fai.services import activity

router = APIRouter(tags=["financial data"])

Pagination = Annotated[PageParams, Depends()]


@router.get("/dashboard", response_model=DashboardSummary, summary="Dashboard summary counts")
async def dashboard(db: DbSession, current_user: CurrentUserDep) -> DashboardSummary:
    current_user.require("data:read")
    summary = await repo.dashboard_summary(db, organization_id=current_user.organization_id)
    return DashboardSummary(**summary)


@router.get("/companies", response_model=Page[CompanyResponse], summary="List companies")
async def list_companies(
    db: DbSession,
    current_user: CurrentUserDep,
    page: Pagination,
    search: Annotated[str | None, Query(max_length=128)] = None,
    sector: Annotated[str | None, Query(max_length=128)] = None,
) -> Page[CompanyResponse]:
    current_user.require("data:read")
    rows, total = await repo.list_companies(
        db,
        organization_id=current_user.organization_id,
        search=search,
        sector=sector,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[CompanyResponse.from_model(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/companies/{company_id}", response_model=CompanyResponse, summary="Fetch one company")
async def get_company(
    company_id: uuid.UUID, db: DbSession, current_user: CurrentUserDep
) -> CompanyResponse:
    current_user.require("data:read")
    company = await repo.get_company(
        db, organization_id=current_user.organization_id, company_id=company_id
    )
    if company is None:
        raise NotFoundError("No such company.")
    return CompanyResponse.from_model(company)


@router.get("/statements", response_model=Page[StatementSummary], summary="List statements")
async def list_statements(
    db: DbSession,
    current_user: CurrentUserDep,
    page: Pagination,
    company_id: uuid.UUID | None = None,
    fiscal_year: Annotated[int | None, Query(ge=1900, le=2200)] = None,
    min_risk_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    has_open_flags: bool | None = None,
) -> Page[StatementSummary]:
    current_user.require("data:read")
    rows, total = await repo.list_statements(
        db,
        organization_id=current_user.organization_id,
        company_id=company_id,
        fiscal_year=fiscal_year,
        min_risk_score=min_risk_score,
        has_open_flags=has_open_flags,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[StatementSummary.from_model(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/statements/{statement_id}",
    response_model=StatementDetail,
    summary="Fetch one statement with line items, ratios, and flags",
)
async def get_statement(
    statement_id: uuid.UUID, db: DbSession, current_user: CurrentUserDep
) -> StatementDetail:
    current_user.require("data:read")
    statement = await repo.get_statement(
        db,
        organization_id=current_user.organization_id,
        statement_id=statement_id,
        with_details=True,
    )
    if statement is None:
        raise NotFoundError("No such statement.")

    # Ratios are recomputed on read rather than stored. They are cheap, and
    # storing them would create a second copy that can drift out of step with
    # the line items after a re-ingest.
    values = {item.tag: item.value for item in statement.line_items}
    ratios = compute_ratios(values)

    detail = StatementDetail.from_model(statement)
    return detail.model_copy(
        update={
            "line_items": [LineItemResponse.model_validate(item) for item in statement.line_items],
            "flags": [AuditFlagResponse.model_validate(flag) for flag in statement.flags],
            "ratios": RatioSet(**ratios.as_dict()),
            "is_fraud_label": statement.is_fraud_label,
        }
    )


@router.get("/flags", response_model=Page[AuditFlagResponse], summary="List audit flags")
async def list_flags(
    db: DbSession,
    current_user: CurrentUserDep,
    page: Pagination,
    statement_id: uuid.UUID | None = None,
    status: FlagStatus | None = None,
    severity: FlagSeverity | None = None,
) -> Page[AuditFlagResponse]:
    current_user.require("data:read")
    rows, total = await repo.list_flags(
        db,
        organization_id=current_user.organization_id,
        statement_id=statement_id,
        status=status,
        severity=severity,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[AuditFlagResponse.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch(
    "/flags/{flag_id}",
    response_model=AuditFlagResponse,
    summary="Triage a flag",
)
async def update_flag(
    flag_id: uuid.UUID,
    payload: UpdateFlagRequest,
    db: DbSession,
    current_user: CurrentUserDep,
    ip: ClientIp,
) -> AuditFlagResponse:
    """Acknowledge, resolve, or dismiss a finding."""
    current_user.require("flags:triage")

    flag = await repo.get_flag(db, organization_id=current_user.organization_id, flag_id=flag_id)
    if flag is None:
        raise NotFoundError("No such flag.")

    previous = flag.status
    flag.status = payload.status

    await activity.record(
        db,
        action=activity.ACTION_FLAG_UPDATED,
        resource_type="audit_flag",
        resource_id=flag.id,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        detail={"from": previous.value, "to": payload.status.value},
        ip_address=ip,
    )
    await db.commit()
    await db.refresh(flag)
    return AuditFlagResponse.model_validate(flag)
