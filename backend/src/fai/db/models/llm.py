"""LLM usage accounting and response cache (Phase 5).

These two tables are what make the free-tier budget hold. ``llm_response_cache``
removes duplicate work, and ``llm_usage_log`` is the meter the provider-failover
logic reads before deciding whether the primary provider still has headroom.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from fai.db.base import Base, UUIDPrimaryKeyMixin
from fai.db.models.enums import LLMCallStatus, LLMProvider, LLMTaskType


class LLMUsageLog(UUIDPrimaryKeyMixin, Base):
    """One row per outbound provider call, successful or not.

    Failed and rate-limited calls are recorded too. A provider that starts
    refusing requests is exactly the signal the failover logic needs, and
    dropping those rows would hide it.
    """

    __tablename__ = "llm_usage_log"
    __table_args__ = (
        # The budget query is "how many calls to provider X since timestamp T".
        # This index is what keeps that check cheap enough to run before every
        # single call.
        Index("ix_llm_usage_provider_created_at", "provider", "created_at"),
        Index("ix_llm_usage_org_created_at", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[LLMProvider] = mapped_column(
        SAEnum(LLMProvider, native_enum=False, length=32), nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[LLMTaskType] = mapped_column(
        SAEnum(LLMTaskType, native_enum=False, length=32), nullable=False
    )
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[LLMCallStatus] = mapped_column(
        SAEnum(LLMCallStatus, native_enum=False, length=32), nullable=False
    )
    # Truncated provider error text. Never the prompt itself: prompts can carry
    # tenant financial data and this table is read for operational dashboards.
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # True when this call happened only because the primary provider was
    # unavailable. Counting these is how the failover rate gets monitored.
    was_fallback: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class LLMResponseCache(UUIDPrimaryKeyMixin, Base):
    """Deduplication cache keyed by the exact inputs that determine a response.

    The key is (prompt_hash, task_type, model). The model is part of the key
    deliberately: the same prompt answered by the fallback model is a different
    response, and serving one under the other would make results irreproducible.

    Cached rows are not scoped to a tenant, which is safe only because the
    prompt hash covers the full prompt text. Two tenants share a cache entry
    only when their prompts were byte-identical, in which case the response
    contains nothing the second tenant did not already supply.
    """

    __tablename__ = "llm_response_cache"
    __table_args__ = (
        UniqueConstraint("prompt_hash", "task_type", "model", name="uq_llm_cache_key"),
    )

    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_type: Mapped[LLMTaskType] = mapped_column(
        SAEnum(LLMTaskType, native_enum=False, length=32), nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[LLMProvider] = mapped_column(
        SAEnum(LLMProvider, native_enum=False, length=32), nullable=False
    )
    # Responses are requested as structured JSON, so the cache stores the parsed
    # object rather than raw text and callers never re-parse.
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Kept for debugging a bad generation after the fact.
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
