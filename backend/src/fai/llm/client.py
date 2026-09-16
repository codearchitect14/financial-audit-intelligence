"""LLM orchestration: cache, budget, failover, and metering.

This is the only place in the codebase that may call a language model. Order of
operations on every request:

1. **Cache.** Keyed by (prompt hash, task type, model). A hit costs nothing and
   returns immediately.
2. **Budget.** Count the primary provider's calls in the trailing day. Over the
   ceiling, skip straight to the fallback rather than burning a request to
   discover the quota is gone.
3. **Primary.** Groq.
4. **Fallback.** Gemini, on a rate limit or an unavailable primary.
5. **Meter.** Every attempt is logged, successful or not.
6. **Cache write.** Only successful responses.

Degradation is deliberate. With no keys configured, cached answers are still
served and new ones raise a clearly-labelled error. Detection, scoring, and
search are unaffected, because none of them depend on this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.config import settings
from fai.core.errors import UpstreamError
from fai.core.logging import get_logger
from fai.db.models import LLMResponseCache, LLMUsageLog
from fai.db.models.enums import LLMCallStatus, LLMProvider, LLMTaskType
from fai.llm.base import (
    MAX_TOKENS,
    LLMRequest,
    LLMResponse,
    Provider,
    ProviderUnavailableError,
    RateLimitError,
)
from fai.llm.providers import GeminiProvider, GroqProvider

log = get_logger(__name__)


@dataclass
class BudgetStatus:
    """What is left of the primary provider's daily allowance."""

    calls_today: int
    ceiling: int

    @property
    def exhausted(self) -> bool:
        return self.calls_today >= self.ceiling

    @property
    def remaining(self) -> int:
        return max(0, self.ceiling - self.calls_today)


class LLMClient:
    """Cached, metered, failing-over access to a language model."""

    def __init__(
        self,
        primary: Provider | None = None,
        fallback: Provider | None = None,
    ):
        self._primary = primary or GroqProvider()
        self._fallback = fallback or GeminiProvider()

    @property
    def available(self) -> bool:
        """True when at least one provider could serve a fresh generation."""
        return self._primary.configured or self._fallback.configured

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    async def _read_cache(
        self, db: AsyncSession, request: LLMRequest, model: str
    ) -> LLMResponseCache | None:
        return (
            await db.execute(
                select(LLMResponseCache).where(
                    LLMResponseCache.prompt_hash == request.prompt_hash,
                    LLMResponseCache.task_type == request.task_type,
                    LLMResponseCache.model == model,
                )
            )
        ).scalar_one_or_none()

    async def _write_cache(
        self, db: AsyncSession, request: LLMRequest, response: LLMResponse
    ) -> None:
        statement = pg_insert(LLMResponseCache).values(
            prompt_hash=request.prompt_hash,
            task_type=request.task_type,
            model=response.model,
            provider=response.provider,
            response_json=response.content,
            raw_response=response.raw[:8000],
            total_tokens=response.total_tokens,
            hit_count=0,
            last_used_at=datetime.now(UTC),
        )
        # Two concurrent identical requests both miss the cache and both try to
        # write. Neither is wrong, so the second is simply ignored.
        statement = statement.on_conflict_do_nothing(constraint="uq_llm_cache_key")
        await db.execute(statement)

    # ------------------------------------------------------------------
    # Budget and metering
    # ------------------------------------------------------------------
    async def budget(self, db: AsyncSession) -> BudgetStatus:
        """Calls made to the primary provider in the trailing 24 hours.

        A rolling window rather than a calendar day: quotas reset on the
        provider's clock, not ours, and a rolling count cannot be gamed by a
        burst just before midnight.
        """
        since = datetime.now(UTC) - timedelta(days=1)
        count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(LLMUsageLog)
                    .where(
                        LLMUsageLog.provider == self._primary.name,
                        LLMUsageLog.created_at >= since,
                    )
                )
            ).scalar_one()
        )
        return BudgetStatus(calls_today=count, ceiling=settings.llm_daily_call_budget)

    async def _meter(
        self,
        db: AsyncSession,
        *,
        request: LLMRequest,
        provider: LLMProvider,
        model: str,
        status: LLMCallStatus,
        organization_id: uuid.UUID | None,
        response: LLMResponse | None = None,
        error: str | None = None,
        was_fallback: bool = False,
    ) -> None:
        """Record one provider attempt.

        Failures are recorded too. A provider that has started refusing
        requests is exactly the signal the failover logic reads, and discarding
        those rows would hide it.

        The prompt itself is never stored, only its hash: prompts carry tenant
        financial data and this table is read for operational dashboards.
        """
        db.add(
            LLMUsageLog(
                organization_id=organization_id,
                provider=provider,
                model=model,
                task_type=request.task_type,
                prompt_hash=request.prompt_hash,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                total_tokens=response.total_tokens if response else 0,
                latency_ms=response.latency_ms if response else None,
                status=status,
                error=error[:512] if error else None,
                was_fallback=was_fallback,
            )
        )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    async def generate(
        self,
        db: AsyncSession,
        request: LLMRequest,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> LLMResponse:
        """Return a generation, from cache where possible."""
        # 1. Cache, checked against both models: an answer from either provider
        #    is a valid answer and there is no reason to pay twice.
        for provider in (self._primary, self._fallback):
            cached = await self._read_cache(db, request, provider.model)
            if cached is not None:
                cached.hit_count += 1
                cached.last_used_at = datetime.now(UTC)
                log.info(
                    "llm_cache_hit",
                    task_type=request.task_type.value,
                    model=cached.model,
                    hit_count=cached.hit_count,
                )
                return LLMResponse(
                    content=cached.response_json,
                    raw=cached.raw_response or "",
                    provider=cached.provider,
                    model=cached.model,
                    total_tokens=cached.total_tokens,
                    cached=True,
                )

        if not self.available:
            raise UpstreamError(
                "No language model is configured, so no new explanation can be "
                "generated. Findings, risk scores, and search are unaffected."
            )

        # 2. Budget. Skipping a doomed call saves latency and keeps the usage
        #    log honest about why the fallback was used.
        status = await self.budget(db)
        attempts: list[tuple[Provider, bool]] = []
        if not status.exhausted and self._primary.configured:
            attempts.append((self._primary, False))
        if self._fallback.configured:
            attempts.append((self._fallback, True))
        if status.exhausted:
            log.warning(
                "llm_primary_budget_exhausted",
                calls_today=status.calls_today,
                ceiling=status.ceiling,
            )

        last_error: Exception | None = None
        for provider, is_fallback in attempts:
            try:
                response = await provider.generate(request)
            except RateLimitError as exc:
                last_error = exc
                await self._meter(
                    db,
                    request=request,
                    provider=provider.name,
                    model=provider.model,
                    status=LLMCallStatus.RATE_LIMITED,
                    organization_id=organization_id,
                    error=str(exc),
                    was_fallback=is_fallback,
                )
                log.warning("llm_rate_limited", provider=provider.name.value, fallback=is_fallback)
                continue
            except (ProviderUnavailableError, Exception) as exc:
                last_error = exc
                await self._meter(
                    db,
                    request=request,
                    provider=provider.name,
                    model=provider.model,
                    status=LLMCallStatus.ERROR,
                    organization_id=organization_id,
                    error=str(exc),
                    was_fallback=is_fallback,
                )
                log.warning(
                    "llm_provider_failed",
                    provider=provider.name.value,
                    error=str(exc),
                    fallback=is_fallback,
                )
                continue

            await self._meter(
                db,
                request=request,
                provider=provider.name,
                model=provider.model,
                status=LLMCallStatus.SUCCESS,
                organization_id=organization_id,
                response=response,
                was_fallback=is_fallback,
            )
            await self._write_cache(db, request, response)

            if is_fallback:
                log.info("llm_served_by_fallback", provider=provider.name.value)

            return LLMResponse(
                content=response.content,
                raw=response.raw,
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                latency_ms=response.latency_ms,
                was_fallback=is_fallback,
            )

        raise UpstreamError(f"Every language model provider failed. Last error: {last_error}")


def request_for(task_type: LLMTaskType, prompt: str) -> LLMRequest:
    """Build a request with the token ceiling for its task type."""
    return LLMRequest(task_type=task_type, prompt=prompt, max_tokens=MAX_TOKENS[task_type])
