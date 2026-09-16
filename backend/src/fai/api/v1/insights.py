"""LLM-backed explanation and question-answering endpoints.

These are the only endpoints in the application that can spend LLM quota, which
is why they carry the tightest rate limits and require an auditor role.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from fai.api.deps import ClientIp, CurrentUserDep, DbSession
from fai.core.rate_limit import limiter
from fai.llm.client import LLMClient
from fai.schemas.finance import AuditFlagResponse
from fai.services import activity, insights

router = APIRouter(tags=["insights"])


def get_llm_client() -> LLMClient:
    """LLM client dependency.

    A dependency rather than a module global so tests can substitute a stub
    through ``app.dependency_overrides`` and never make a real provider call.
    """
    return LLMClient()


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]


class ExplainRequest(BaseModel):
    statement_id: uuid.UUID
    force: bool = Field(
        default=False,
        description="Regenerate explanations that already exist. Costs quota.",
    )


class ExplainResponse(BaseModel):
    statement_id: uuid.UUID
    flags: list[AuditFlagResponse]
    explained_count: int


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    passages: int = Field(default=8, ge=1, le=20)


class SourceRef(BaseModel):
    index: int
    document_id: str
    document_name: str
    similarity: float
    excerpt: str


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[int]
    sufficient_context: bool = Field(
        description="False when the retrieved passages do not support an answer."
    )
    sources: list[SourceRef]
    cached: bool


class BudgetResponse(BaseModel):
    calls_today: int
    ceiling: int
    remaining: int
    exhausted: bool
    providers_configured: bool


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Explain a statement's findings in plain language",
)
# One call per statement, not per finding, but still the most expensive
# endpoint in the application.
@limiter.limit("30/hour")
async def explain(
    request: Request,
    payload: ExplainRequest,
    db: DbSession,
    current_user: CurrentUserDep,
    client: LLMClientDep,
    ip: ClientIp,
) -> ExplainResponse:
    """Generate explanations for every unexplained finding on a statement.

    All findings are batched into a single model call. Results are cached, so
    re-opening the same statement costs nothing.
    """
    current_user.require("analysis:run")

    flags = await insights.explain_statement_findings(
        db,
        statement_id=payload.statement_id,
        organization_id=current_user.organization_id,
        client=client,
        force=payload.force,
    )

    await activity.record(
        db,
        action=activity.ACTION_EXPLANATION_REQUESTED,
        resource_type="financial_statement",
        resource_id=payload.statement_id,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        ip_address=ip,
    )
    await db.commit()

    return ExplainResponse(
        statement_id=payload.statement_id,
        flags=[AuditFlagResponse.model_validate(flag) for flag in flags],
        explained_count=sum(1 for flag in flags if flag.explanation),
    )


@router.post("/ask", response_model=AskResponse, summary="Ask a question of the corpus")
@limiter.limit("60/hour")
async def ask(
    request: Request,
    payload: AskRequest,
    db: DbSession,
    current_user: CurrentUserDep,
    client: LLMClientDep,
) -> AskResponse:
    """Answer a natural-language question from indexed passages.

    Retrieval runs first and is free; only the top passages reach the model.
    When nothing relevant is retrieved, no model call is made at all.
    """
    current_user.require("data:read")

    result = await insights.answer_question(
        db,
        question=payload.question,
        organization_id=current_user.organization_id,
        client=client,
        passages=payload.passages,
    )

    return AskResponse(
        question=payload.question,
        answer=result["answer"],
        citations=result["citations"],
        sufficient_context=result["sufficient_context"],
        sources=[SourceRef(**source) for source in result["sources"]],
        cached=result["cached"],
    )


@router.get("/llm/budget", response_model=BudgetResponse, summary="LLM quota status")
async def budget(
    db: DbSession, current_user: CurrentUserDep, client: LLMClientDep
) -> BudgetResponse:
    """Report how much of the primary provider's daily allowance remains."""
    current_user.require("data:read")
    status = await client.budget(db)
    return BudgetResponse(
        calls_today=status.calls_today,
        ceiling=status.ceiling,
        remaining=status.remaining,
        exhausted=status.exhausted,
        providers_configured=client.available,
    )
