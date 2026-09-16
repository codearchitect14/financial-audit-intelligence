"""Explanation and question-answering services.

The batching rule lives here: every finding on a statement is explained by one
LLM call, not one call per finding.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.errors import NotFoundError, ValidationError
from fai.core.logging import get_logger
from fai.db.models import AuditFlag, FinancialStatement
from fai.db.models.enums import LLMTaskType
from fai.llm.client import LLMClient, request_for
from fai.llm.prompts import anomaly_explanation_prompt, question_answer_prompt
from fai.repositories import finance as repo
from fai.search.service import search as vector_search

log = get_logger(__name__)

# Explaining more than this in one prompt risks truncating the response against
# the task's token ceiling, which would silently drop the last few findings.
MAX_FINDINGS_PER_CALL = 12

# Passages sent to the model for a question. Beyond roughly ten, added context
# costs tokens without improving the answer.
DEFAULT_CONTEXT_PASSAGES = 8


async def explain_statement_findings(
    db: AsyncSession,
    *,
    statement_id: uuid.UUID,
    organization_id: uuid.UUID,
    client: LLMClient,
    force: bool = False,
) -> list[AuditFlag]:
    """Explain every unexplained finding on a statement in a single call.

    Findings that already carry an explanation are skipped unless ``force`` is
    set, so re-opening a statement in the UI costs nothing.
    """
    statement = await repo.get_statement(
        db, organization_id=organization_id, statement_id=statement_id, with_details=True
    )
    if statement is None:
        raise NotFoundError("No such statement.")

    candidates = [flag for flag in statement.flags if force or flag.explanation is None][
        :MAX_FINDINGS_PER_CALL
    ]

    if not candidates:
        return list(statement.flags)

    prompt = anomaly_explanation_prompt(
        company_name=statement.company.name if statement.company else "Unknown",
        fiscal_year=statement.fiscal_year,
        fiscal_period=statement.fiscal_period.value,
        findings=[
            {
                "flag_type": flag.flag_type,
                "severity": flag.severity.value,
                "description": flag.description,
                "detail": flag.detail,
            }
            for flag in candidates
        ],
    )

    response = await client.generate(
        db,
        request_for(LLMTaskType.ANOMALY_EXPLANATION, prompt),
        organization_id=organization_id,
    )

    explanations = response.content.get("explanations")
    if not isinstance(explanations, list):
        raise ValidationError("The model response did not contain an explanations list.")

    by_index: dict[int, str] = {}
    for entry in explanations:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index", 0))
        except (TypeError, ValueError):
            continue
        text = entry.get("explanation")
        if isinstance(text, str) and text.strip():
            by_index[index] = text.strip()

    now = datetime.now(UTC)
    for position, flag in enumerate(candidates, start=1):
        explanation = by_index.get(position)
        if explanation:
            flag.explanation = explanation
            flag.explained_at = now

    await db.commit()

    log.info(
        "findings_explained",
        statement_id=str(statement_id),
        explained=len(by_index),
        requested=len(candidates),
        cached=response.cached,
        fallback=response.was_fallback,
    )

    refreshed = await repo.get_statement(
        db, organization_id=organization_id, statement_id=statement_id, with_details=True
    )
    return list(refreshed.flags) if refreshed else []


async def answer_question(
    db: AsyncSession,
    *,
    question: str,
    organization_id: uuid.UUID,
    client: LLMClient,
    passages: int = DEFAULT_CONTEXT_PASSAGES,
) -> dict[str, Any]:
    """Answer a natural-language question from retrieved passages.

    Retrieval runs first and costs nothing. Only the top passages reach the
    model, so token cost is bounded by the context size rather than by the
    corpus.
    """
    hits = await vector_search(db, question, organization_id=organization_id, limit=passages)

    if not hits:
        # No retrieval, no call. Asking a model to answer from an empty context
        # spends quota to produce a guess.
        return {
            "answer": (
                "No indexed passages matched this question. Upload and index "
                "relevant documents first."
            ),
            "citations": [],
            "sufficient_context": False,
            "sources": [],
            "cached": False,
        }

    prompt = question_answer_prompt(
        question=question,
        passages=[{"text": hit.text, "document_name": hit.document_name} for hit in hits],
    )

    response = await client.generate(
        db,
        request_for(LLMTaskType.QUESTION_ANSWER, prompt),
        organization_id=organization_id,
    )
    await db.commit()

    citations = response.content.get("citations")
    if not isinstance(citations, list):
        citations = []

    return {
        "answer": str(response.content.get("answer", "")),
        "citations": [int(c) for c in citations if isinstance(c, int | str) and str(c).isdigit()],
        "sufficient_context": bool(response.content.get("sufficient_context", False)),
        "sources": [
            {
                "index": index,
                "document_id": str(hit.document_id),
                "document_name": hit.document_name,
                "similarity": hit.similarity,
                "excerpt": hit.text[:300],
            }
            for index, hit in enumerate(hits, start=1)
        ],
        "cached": response.cached,
        "provider": response.provider.value,
        "was_fallback": response.was_fallback,
    }


async def statement_flags(db: AsyncSession, statement_id: uuid.UUID) -> Sequence[AuditFlag]:
    """Flags for a statement. Caller must have resolved the statement first."""
    return (
        (await db.execute(select(AuditFlag).where(AuditFlag.statement_id == statement_id)))
        .scalars()
        .all()
    )


async def statement_exists(
    db: AsyncSession, statement_id: uuid.UUID, organization_id: uuid.UUID
) -> bool:
    statement = await repo.get_statement(
        db, organization_id=organization_id, statement_id=statement_id
    )
    return statement is not None


__all__ = [
    "DEFAULT_CONTEXT_PASSAGES",
    "MAX_FINDINGS_PER_CALL",
    "FinancialStatement",
    "answer_question",
    "explain_statement_findings",
    "statement_exists",
    "statement_flags",
]
