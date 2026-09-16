"""Report generation and export endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from fai.api.deps import ClientIp, CurrentUserDep, DbSession
from fai.api.v1.insights import LLMClientDep
from fai.core.errors import NotFoundError, ValidationError
from fai.core.rate_limit import limiter
from fai.db.models.enums import ReportStatus
from fai.reporting import builder, renderer
from fai.schemas.common import Page, PageParams
from fai.services import activity

router = APIRouter(prefix="/reports", tags=["reports"])

Pagination = Annotated[PageParams, Depends()]


class GenerateReportRequest(BaseModel):
    statement_id: uuid.UUID
    include_narrative: bool = Field(
        default=True,
        description=(
            "Generate LLM narrative sections. Set false to produce a figures-only "
            "report at no quota cost."
        ),
    )


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement_id: uuid.UUID
    title: str
    status: ReportStatus
    risk_score: float | None
    created_at: datetime
    generated_at: datetime | None


class ReportDetail(ReportSummary):
    content: dict[str, Any]
    narrative_available: bool = False
    error: str | None = None


class ExportFormatsResponse(BaseModel):
    html: bool
    pdf: bool
    pdf_unavailable_reason: str | None = None


@router.post(
    "",
    response_model=ReportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an audit report",
)
# Up to three narrative calls per report, so this is quota-bearing.
@limiter.limit("20/hour")
async def generate(
    request: Request,
    payload: GenerateReportRequest,
    db: DbSession,
    current_user: CurrentUserDep,
    client: LLMClientDep,
    ip: ClientIp,
) -> ReportDetail:
    """Assemble a report from computed figures and persisted findings.

    Every number comes from stored data. The model contributes narrative only,
    and a failure to generate it produces a complete figures-only report rather
    than failing the request.
    """
    current_user.require("reports:generate")

    report = await builder.generate_report(
        db,
        statement_id=payload.statement_id,
        organization_id=current_user.organization_id,
        generated_by=current_user.id,
        client=client,
        include_narrative=payload.include_narrative,
    )

    await activity.record(
        db,
        action=activity.ACTION_REPORT_GENERATED,
        resource_type="audit_report",
        resource_id=report.id,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        detail={"statement_id": str(payload.statement_id)},
        ip_address=ip,
    )
    await db.commit()
    await db.refresh(report)

    return _to_detail(report)


@router.get("", response_model=Page[ReportSummary], summary="List reports")
async def list_reports(
    db: DbSession, current_user: CurrentUserDep, page: Pagination
) -> Page[ReportSummary]:
    current_user.require("data:read")
    rows, total = await builder.list_reports(
        db,
        organization_id=current_user.organization_id,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[ReportSummary.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/formats", response_model=ExportFormatsResponse, summary="Export formats")
async def formats(current_user: CurrentUserDep) -> ExportFormatsResponse:
    """Report which export formats this deployment can produce.

    The frontend reads this to decide whether to offer a PDF button, rather
    than offering one that fails when the native libraries are absent.
    """
    current_user.require("data:read")
    available = renderer.pdf_available()
    return ExportFormatsResponse(
        html=True,
        pdf=available,
        pdf_unavailable_reason=(
            None
            if available
            else "WeasyPrint is not installed, or its native Pango and Cairo "
            "libraries are missing on this host."
        ),
    )


@router.get("/{report_id}", response_model=ReportDetail, summary="Fetch one report")
async def get_report(
    report_id: uuid.UUID, db: DbSession, current_user: CurrentUserDep
) -> ReportDetail:
    current_user.require("data:read")
    report = await builder.get_report(
        db, organization_id=current_user.organization_id, report_id=report_id
    )
    if report is None:
        raise NotFoundError("No such report.")
    return _to_detail(report)


@router.get(
    "/{report_id}/export",
    summary="Export a report as HTML or PDF",
    response_class=Response,
)
async def export(
    report_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUserDep,
    fmt: Annotated[str, Field(pattern="^(html|pdf)$")] = "html",
) -> Response:
    """Render a stored report.

    Rendering reads the persisted JSON, so an export never re-runs a model and
    always reproduces the report as generated.
    """
    current_user.require("data:read")

    report = await builder.get_report(
        db, organization_id=current_user.organization_id, report_id=report_id
    )
    if report is None:
        raise NotFoundError("No such report.")

    if fmt == "html":
        return Response(
            content=renderer.render_html(report.content, report.title),
            media_type="text/html; charset=utf-8",
        )

    if fmt == "pdf":
        if not renderer.pdf_available():
            raise ValidationError("PDF export is unavailable on this host. Export as HTML instead.")
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = renderer.render_pdf(
                report.content, report.title, Path(directory) / f"{report_id}.pdf"
            )
            body = path.read_bytes()

        # A filename derived from the report id, never from the title: the
        # title contains a company name and would need escaping in the header.
        return Response(
            content=body,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="report-{report_id}.pdf"'},
        )

    raise ValidationError("fmt must be 'html' or 'pdf'.")


def _to_detail(report: object) -> ReportDetail:
    detail = ReportDetail.model_validate(report, from_attributes=True)
    content = getattr(report, "content", {}) or {}
    return detail.model_copy(
        update={
            "content": content,
            "narrative_available": bool(content.get("narrative_available")),
            "error": getattr(report, "error", None),
        }
    )
