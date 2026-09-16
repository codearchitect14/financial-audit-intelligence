"""Semantic search endpoint.

Returns passages, never answers. No LLM is called here, which is what makes
this endpoint free to run, instant, and safe to expose without a token budget.
Turning retrieved passages into prose is a separate, explicitly-requested
operation in Phase 5.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from fai.api.deps import CurrentUserDep, DbSession
from fai.core.rate_limit import limiter
from fai.search.service import search as run_search

router = APIRouter(prefix="/search", tags=["search"])

MAX_QUERY_LENGTH = 1000
MAX_RESULTS = 50


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    chunk_index: int
    text: str
    similarity: float = Field(description="Cosine similarity in 0-1. Higher is a closer match.")


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    count: int


@router.get("", response_model=SearchResponse, summary="Search indexed passages")
# Each call runs one embedding forward pass. Cheap, but not free, and trivially
# scriptable into a CPU-exhaustion attack on a small instance.
@limiter.limit("120/minute")
async def search(
    request: Request,
    db: DbSession,
    current_user: CurrentUserDep,
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH)],
    limit: Annotated[int, Query(ge=1, le=MAX_RESULTS)] = 10,
    document_id: uuid.UUID | None = None,
) -> SearchResponse:
    """Find the passages most similar to a natural-language query.

    Results are always restricted to the caller's organization.
    """
    current_user.require("data:read")

    hits = await run_search(
        db,
        q,
        organization_id=current_user.organization_id,
        limit=limit,
        document_id=document_id,
    )

    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_name=hit.document_name,
                chunk_index=hit.chunk_index,
                text=hit.text,
                similarity=hit.similarity,
            )
            for hit in hits
        ],
        count=len(hits),
    )
