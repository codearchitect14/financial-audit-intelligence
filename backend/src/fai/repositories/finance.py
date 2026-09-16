"""Tenant-scoped queries over financial data.

Every function here takes an ``organization_id`` and applies the visibility rule
itself. Endpoints never build their own filters, because a single forgotten
``WHERE`` clause in one handler is all it takes to leak another tenant's data.

Visibility rule, as described in docs/data-model.md:

* reference tables (``companies``, ``financial_statements``) are visible when
  ``organization_id`` matches the caller **or is NULL**, NULL meaning the shared
  public SEC corpus;
* private tables are visible only on an exact match.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fai.db.models import (
    AuditFlag,
    Company,
    FinancialLineItem,
    FinancialStatement,
)
from fai.db.models.enums import FlagSeverity, FlagStatus


def visible_companies(organization_id: uuid.UUID) -> Select[tuple[Company]]:
    """Companies this tenant may see: its own, plus the public corpus."""
    return select(Company).where(
        or_(Company.organization_id == organization_id, Company.organization_id.is_(None))
    )


def visible_statements(organization_id: uuid.UUID) -> Select[tuple[FinancialStatement]]:
    """Statements this tenant may see: its own, plus the public corpus."""
    return select(FinancialStatement).where(
        or_(
            FinancialStatement.organization_id == organization_id,
            FinancialStatement.organization_id.is_(None),
        )
    )


async def _total(db: AsyncSession, query: Select[Any]) -> int:
    """Count rows a query would return, without its ordering or pagination."""
    subquery = query.order_by(None).subquery()
    return int((await db.execute(select(func.count()).select_from(subquery))).scalar_one())


async def list_companies(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    search: str | None = None,
    sector: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Company], int]:
    query = visible_companies(organization_id)

    if search:
        # ILIKE with a bound parameter. The wildcards are added here rather than
        # taken from the caller, so a user-supplied '%' cannot turn into a full
        # table scan by accident.
        query = query.where(
            or_(
                Company.name.ilike(f"%{search}%"),
                Company.ticker.ilike(f"{search}%"),
                Company.cik == search.zfill(10),
            )
        )
    if sector:
        query = query.where(Company.sector == sector)

    total = await _total(db, query)
    rows = (
        (await db.execute(query.order_by(Company.name).limit(limit).offset(offset))).scalars().all()
    )
    return rows, total


async def get_company(
    db: AsyncSession, *, organization_id: uuid.UUID, company_id: uuid.UUID
) -> Company | None:
    query = visible_companies(organization_id).where(Company.id == company_id)
    return (await db.execute(query)).scalar_one_or_none()


async def list_statements(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    fiscal_year: int | None = None,
    min_risk_score: float | None = None,
    has_open_flags: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[FinancialStatement], int]:
    query = visible_statements(organization_id).options(
        # Eager-loaded: the list view renders the company name for every row,
        # and lazy loading would issue one query per statement.
        selectinload(FinancialStatement.company)
    )

    if company_id is not None:
        query = query.where(FinancialStatement.company_id == company_id)
    if fiscal_year is not None:
        query = query.where(FinancialStatement.fiscal_year == fiscal_year)
    if min_risk_score is not None:
        query = query.where(FinancialStatement.risk_score >= min_risk_score)
    if has_open_flags:
        query = query.where(
            select(AuditFlag.id)
            .where(
                AuditFlag.statement_id == FinancialStatement.id,
                AuditFlag.status == FlagStatus.OPEN,
            )
            .exists()
        )

    total = await _total(db, query)
    rows = (
        (
            await db.execute(
                query.order_by(
                    # Highest risk first, with unscored statements last rather
                    # than sorted as if they were zero risk.
                    FinancialStatement.risk_score.desc().nullslast(),
                    FinancialStatement.fiscal_year.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return rows, total


async def get_statement(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    statement_id: uuid.UUID,
    with_details: bool = False,
) -> FinancialStatement | None:
    query = visible_statements(organization_id).where(FinancialStatement.id == statement_id)
    if with_details:
        query = query.options(
            selectinload(FinancialStatement.company),
            selectinload(FinancialStatement.line_items),
            selectinload(FinancialStatement.flags),
        )
    return (await db.execute(query)).scalar_one_or_none()


async def get_line_items(
    db: AsyncSession, *, statement_id: uuid.UUID
) -> Sequence[FinancialLineItem]:
    """Line items for a statement.

    Not tenant-scoped itself: callers must have already resolved the statement
    through ``get_statement``, which is scoped. Calling this with an
    unvalidated id would bypass tenancy.
    """
    return (
        (
            await db.execute(
                select(FinancialLineItem)
                .where(FinancialLineItem.statement_id == statement_id)
                .order_by(FinancialLineItem.statement_section, FinancialLineItem.tag)
            )
        )
        .scalars()
        .all()
    )


async def list_flags(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    statement_id: uuid.UUID | None = None,
    status: FlagStatus | None = None,
    severity: FlagSeverity | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[AuditFlag], int]:
    """Flags, joined through statements so the tenant filter still applies."""
    query = (
        select(AuditFlag)
        .join(FinancialStatement, AuditFlag.statement_id == FinancialStatement.id)
        .where(
            or_(
                FinancialStatement.organization_id == organization_id,
                FinancialStatement.organization_id.is_(None),
            )
        )
    )

    if statement_id is not None:
        query = query.where(AuditFlag.statement_id == statement_id)
    if status is not None:
        query = query.where(AuditFlag.status == status)
    if severity is not None:
        query = query.where(AuditFlag.severity == severity)

    total = await _total(db, query)
    rows = (
        (await db.execute(query.order_by(AuditFlag.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return rows, total


async def get_flag(
    db: AsyncSession, *, organization_id: uuid.UUID, flag_id: uuid.UUID
) -> AuditFlag | None:
    query = (
        select(AuditFlag)
        .join(FinancialStatement, AuditFlag.statement_id == FinancialStatement.id)
        .where(
            AuditFlag.id == flag_id,
            or_(
                FinancialStatement.organization_id == organization_id,
                FinancialStatement.organization_id.is_(None),
            ),
        )
    )
    return (await db.execute(query)).scalar_one_or_none()


async def dashboard_summary(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> dict[str, int | float | None]:
    """Counts for the dashboard landing page, in one round trip each."""
    statements_query = visible_statements(organization_id)

    total_statements = await _total(db, statements_query)

    open_flags = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AuditFlag)
                .join(FinancialStatement, AuditFlag.statement_id == FinancialStatement.id)
                .where(
                    AuditFlag.status == FlagStatus.OPEN,
                    or_(
                        FinancialStatement.organization_id == organization_id,
                        FinancialStatement.organization_id.is_(None),
                    ),
                )
            )
        ).scalar_one()
    )

    critical_flags = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AuditFlag)
                .join(FinancialStatement, AuditFlag.statement_id == FinancialStatement.id)
                .where(
                    AuditFlag.status == FlagStatus.OPEN,
                    AuditFlag.severity.in_([FlagSeverity.HIGH, FlagSeverity.CRITICAL]),
                    or_(
                        FinancialStatement.organization_id == organization_id,
                        FinancialStatement.organization_id.is_(None),
                    ),
                )
            )
        ).scalar_one()
    )

    high_risk = await _total(db, statements_query.where(FinancialStatement.risk_score >= 70))

    average_risk = (
        await db.execute(
            select(func.avg(FinancialStatement.risk_score)).where(
                FinancialStatement.risk_score.isnot(None),
                or_(
                    FinancialStatement.organization_id == organization_id,
                    FinancialStatement.organization_id.is_(None),
                ),
            )
        )
    ).scalar_one()

    return {
        "total_statements": total_statements,
        "open_flags": open_flags,
        "critical_flags": critical_flags,
        "high_risk_statements": high_risk,
        "average_risk_score": round(float(average_risk), 2) if average_risk else None,
    }
