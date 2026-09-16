"""Audit report assembly.

A report is built from figures that already exist: computed ratios, persisted
findings, and the stored risk score. The LLM is asked only for connecting
narrative, and only after every number is fixed.

That ordering is what makes a report defensible. The arithmetic is not
generated, so it cannot be hallucinated; regenerating the prose cannot change a
single figure; and a report produced with no LLM configured at all is still
complete and correct, just without the narrative sections.

The stored form is structured JSON rather than rendered prose, so a report can
be re-rendered into a new template or exported in another format without asking
a model to write anything twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.errors import NotFoundError
from fai.core.logging import get_logger
from fai.db.models import AuditReport, FinancialStatement
from fai.db.models.enums import FlagSeverity, FlagStatus, LLMTaskType, ReportStatus
from fai.detection.ratios import compute_ratios
from fai.llm.client import LLMClient, request_for
from fai.llm.prompts import report_section_prompt
from fai.repositories import finance as repo

log = get_logger(__name__)

# Report schema version. Stored on every report so that a future template can
# tell which shape it is rendering and old reports stay readable.
SCHEMA_VERSION = 1

SEVERITY_ORDER = {
    FlagSeverity.CRITICAL: 0,
    FlagSeverity.HIGH: 1,
    FlagSeverity.MEDIUM: 2,
    FlagSeverity.LOW: 3,
    FlagSeverity.INFO: 4,
}

# Narrative sections. Each costs one LLM call, so the list is deliberately
# short: three calls per report, cached thereafter.
NARRATIVE_SECTIONS = ("Executive summary", "Risk assessment", "Recommended procedures")


def _format_money(value: Decimal) -> str:
    """Render an exact decimal without meaningless trailing zeros.

    The column is Numeric(28, 4), so str() renders 1000000 as "1000000.0000".
    Exactness is preserved here, only the padding is dropped: normalize() alone
    would produce scientific notation ("1E+6"), which is worse in a report than
    the padding was.
    """
    return format(value.normalize(), "f")


def _risk_band(score: float | None) -> str:
    """Bucket a score into a label a reader can act on."""
    if score is None:
        return "not assessed"
    if score >= 70:
        return "high"
    if score >= 40:
        return "elevated"
    if score > 0:
        return "low"
    return "no findings"


def build_facts(statement: FinancialStatement) -> dict[str, Any]:
    """Assemble every computed figure the report will cite.

    This is the complete factual basis. Anything the narrative mentions must
    appear here, which is what the prompt instructs and what makes the
    generated prose checkable against the data.
    """
    values = {item.tag: item.value for item in statement.line_items}
    ratios = compute_ratios(values)

    flags = sorted(
        statement.flags,
        key=lambda flag: (SEVERITY_ORDER.get(flag.severity, 9), flag.flag_type),
    )
    open_flags = [flag for flag in flags if flag.status is FlagStatus.OPEN]

    return {
        "schema_version": SCHEMA_VERSION,
        "company": {
            "name": statement.company.name if statement.company else "Unknown",
            "cik": statement.company.cik if statement.company else None,
            "sector": statement.company.sector if statement.company else None,
        },
        "period": {
            "fiscal_year": statement.fiscal_year,
            "fiscal_period": statement.fiscal_period.value,
            "filing_type": statement.filing_type.value,
            "period_end_date": (
                statement.period_end_date.isoformat() if statement.period_end_date else None
            ),
        },
        "risk": {
            "score": statement.risk_score,
            "band": _risk_band(statement.risk_score),
            "scored_at": (
                statement.risk_scored_at.isoformat() if statement.risk_scored_at else None
            ),
            # Stated in the data itself, not only in the template, so it
            # survives any re-rendering.
            "basis": (
                "A triage ordering derived from deterministic checks. It is not a "
                "probability of fraud and is not a conclusion."
            ),
        },
        "ratios": ratios.as_dict(),
        "findings": [
            {
                "flag_type": flag.flag_type,
                "severity": flag.severity.value,
                "status": flag.status.value,
                "detection_method": flag.detection_method.value,
                "description": flag.description,
                "detail": flag.detail,
                "explanation": flag.explanation,
            }
            for flag in flags
        ],
        "counts": {
            "total_findings": len(flags),
            "open_findings": len(open_flags),
            "by_severity": {
                severity.value: sum(1 for f in flags if f.severity is severity)
                for severity in FlagSeverity
            },
        },
        "line_items": {tag: _format_money(value) for tag, value in sorted(values.items())},
    }


async def generate_report(
    db: AsyncSession,
    *,
    statement_id: uuid.UUID,
    organization_id: uuid.UUID,
    generated_by: uuid.UUID | None,
    client: LLMClient | None = None,
    include_narrative: bool = True,
) -> AuditReport:
    """Build and persist a report for one statement.

    ``include_narrative=False``, or an unavailable LLM, produces a complete
    report without the prose sections. Every figure is present either way.
    """
    statement = await repo.get_statement(
        db, organization_id=organization_id, statement_id=statement_id, with_details=True
    )
    if statement is None:
        raise NotFoundError("No such statement.")

    facts = build_facts(statement)
    company_name = facts["company"]["name"]
    title = (
        f"Audit report: {company_name}, "
        f"{facts['period']['fiscal_year']} {facts['period']['fiscal_period']}"
    )

    report = AuditReport(
        organization_id=organization_id,
        statement_id=statement_id,
        generated_by=generated_by,
        title=title,
        status=ReportStatus.GENERATING,
        content={},
        # Snapshotted here. The live score moves as detectors are tuned; a
        # report that has been read and acted on must not.
        risk_score=statement.risk_score,
    )
    db.add(report)
    await db.flush()

    sections: list[dict[str, Any]] = []
    narrative_error: str | None = None

    if include_narrative and client is not None and client.available:
        for section in NARRATIVE_SECTIONS:
            try:
                response = await client.generate(
                    db,
                    request_for(
                        LLMTaskType.REPORT_SECTION,
                        report_section_prompt(
                            company_name=company_name,
                            fiscal_year=facts["period"]["fiscal_year"],
                            section=section,
                            facts=_facts_for_section(facts, section),
                        ),
                    ),
                    organization_id=organization_id,
                )
                sections.append(
                    {
                        "section": section,
                        "heading": str(response.content.get("heading", section)),
                        "body": str(response.content.get("body", "")),
                        "generated": True,
                        "cached": response.cached,
                    }
                )
            except Exception as exc:
                # A failed narrative must not fail the report. The figures are
                # the substance; the prose is presentation.
                narrative_error = str(exc)[:500]
                log.warning("report_narrative_failed", section=section, error=str(exc))
                break

    report.content = {
        "schema_version": SCHEMA_VERSION,
        "facts": facts,
        "narrative": sections,
        "narrative_available": bool(sections),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    report.status = ReportStatus.COMPLETE
    report.generated_at = datetime.now(UTC)
    report.error = narrative_error

    await db.flush()
    log.info(
        "report_generated",
        report_id=str(report.id),
        statement_id=str(statement_id),
        narrative_sections=len(sections),
    )
    return report


def _facts_for_section(facts: dict[str, Any], section: str) -> dict[str, Any]:
    """Narrow the facts to what one section needs.

    Sending the whole payload to every section would triple the prompt tokens
    for no benefit, and the model writes tighter prose from a focused brief.
    """
    common = {"company": facts["company"], "period": facts["period"], "risk": facts["risk"]}

    if section == "Executive summary":
        return {**common, "counts": facts["counts"]}
    if section == "Risk assessment":
        return {
            **common,
            "counts": facts["counts"],
            # Only the material findings; the tail adds tokens, not meaning.
            "findings": [
                {k: v for k, v in finding.items() if k != "detail"}
                for finding in facts["findings"][:8]
            ],
            "ratios": {k: v for k, v in facts["ratios"].items() if v is not None},
        }
    return {
        **common,
        "findings": [
            {"flag_type": f["flag_type"], "severity": f["severity"]} for f in facts["findings"][:8]
        ],
    }


async def list_reports(
    db: AsyncSession, *, organization_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[AuditReport], int]:
    """Reports belonging to one organization."""
    from sqlalchemy import func

    base = select(AuditReport).where(AuditReport.organization_id == organization_id)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = list(
        (await db.execute(base.order_by(AuditReport.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return rows, total


async def get_report(
    db: AsyncSession, *, organization_id: uuid.UUID, report_id: uuid.UUID
) -> AuditReport | None:
    return (
        await db.execute(
            select(AuditReport).where(
                AuditReport.id == report_id,
                AuditReport.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
