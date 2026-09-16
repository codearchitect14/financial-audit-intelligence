"""Groq and Gemini backends.

Both are called over their public REST APIs with httpx. No vendor SDK: each
would add a dependency tree and its own retry behaviour for two endpoints that
are a single POST each, and the failover logic needs to see raw status codes
rather than an SDK's normalised exceptions.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from fai.core.config import settings
from fai.core.logging import get_logger
from fai.db.models.enums import LLMProvider
from fai.llm.base import (
    LLMRequest,
    LLMResponse,
    ProviderUnavailableError,
    RateLimitError,
    extract_json,
)

log = get_logger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Generous enough for a cold model, short enough that a hung provider does not
# hold a request open until the platform's own timeout kills it.
TIMEOUT = httpx.Timeout(10.0, read=60.0)


class GroqProvider:
    """Primary provider. OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or (
            settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
        )
        self._model = model or settings.groq_model

    @property
    def name(self) -> LLMProvider:
        return LLMProvider.GROQ

    @property
    def model(self) -> str:
        return self._model

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.configured:
            raise ProviderUnavailableError("GROQ_API_KEY is not configured.")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": request.max_tokens,
            # Zero temperature: an audit tool that returns a different
            # explanation for the same finding on each run is not defensible,
            # and it would also defeat the response cache.
            "temperature": request.temperature,
            "response_format": {"type": "json_object"},
        }

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Groq request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code == 429:
            raise RateLimitError("Groq rate limit reached.")
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"Groq returned {response.status_code}: {response.text[:200]}"
            )

        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError("Groq returned an unexpected shape.") from exc

        usage = body.get("usage") or {}
        return LLMResponse(
            content=extract_json(text),
            raw=text,
            provider=self.name,
            model=self._model,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            latency_ms=latency_ms,
        )


class GeminiProvider:
    """Fallback provider."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or (
            settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        )
        self._model = model or settings.gemini_model

    @property
    def name(self) -> LLMProvider:
        return LLMProvider.GEMINI

    @property
    def model(self) -> str:
        return self._model

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.configured:
            raise ProviderUnavailableError("GEMINI_API_KEY is not configured.")

        payload: dict[str, Any] = {
            # Gemini has no system role; the instruction goes in its own field.
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
                "responseMimeType": "application/json",
            },
        }

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    f"{GEMINI_URL}/{self._model}:generateContent",
                    # The key goes in a header, not the query string: a URL
                    # carrying a credential ends up in proxy and access logs.
                    headers={
                        "x-goog-api-key": self._api_key or "",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Gemini request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code == 429:
            raise RateLimitError("Gemini rate limit reached.")
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"Gemini returned {response.status_code}: {response.text[:200]}"
            )

        body = response.json()
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            # A response blocked by a safety filter has this shape too, and the
            # reason is worth surfacing rather than reporting as a generic
            # failure.
            reason = (body.get("promptFeedback") or {}).get("blockReason")
            raise ProviderUnavailableError(
                f"Gemini returned no usable candidate{f' ({reason})' if reason else ''}."
            ) from exc

        usage = body.get("usageMetadata") or {}
        return LLMResponse(
            content=extract_json(text),
            raw=text,
            provider=self.name,
            model=self._model,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            total_tokens=int(usage.get("totalTokenCount", 0)),
            latency_ms=latency_ms,
        )
