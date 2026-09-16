"""Shared test fixtures.

The unit-level suite runs with no database. Tests that genuinely need Postgres
are marked ``@pytest.mark.integration`` and are skipped unless a live database
is reachable, so that ``pytest`` is always runnable on a clean checkout.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest

# Settings are read once at import time, so any override has to be in place
# before the application package is imported.
os.environ.setdefault("ENVIRONMENT", "ci")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-used-in-any-deployment")
# A suite of login cases would otherwise trip the production rate limit and
# start failing for a reason that has nothing to do with the behaviour under
# test. The limiter itself is covered by its own test, which enables it.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import httpx
from fastapi import FastAPI

from fai.main import create_app


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client bound to the app in-process, with lifespan run.

    ASGITransport dispatches straight into the application, so the suite
    exercises the real middleware and exception-handler stack without binding a
    socket.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _database_available() -> bool:
    """Probe the configured database without importing test-time engines."""
    try:
        import psycopg

        from fai.core.config import settings

        with psycopg.connect(str(settings.database_url), connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def require_database() -> Iterator[None]:
    if not _database_available():
        pytest.skip("no database reachable; start it with: docker compose up -d db")
    yield
