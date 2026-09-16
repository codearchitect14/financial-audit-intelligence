"""Database engines and session factories.

Two engines exist deliberately:

* an **async** engine (asyncpg) used by the FastAPI request path, where the
  workload is IO bound and concurrency matters;
* a **sync** engine (psycopg 3) used by Alembic and by the batch ingestion and
  scoring jobs, which are driven by pandas and scikit-learn and have no reason
  to be asynchronous.

Both read the same DSN from settings, so a deployment configures one value.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from fai.core.config import settings


def _async_engine_kwargs() -> dict[str, object]:
    """Pool configuration for the async engine.

    Under test the pool is disabled entirely. An asyncpg connection is bound to
    the event loop that created it, and the test runner builds a fresh loop per
    test; a pooled connection therefore gets handed to a later test whose loop
    is different, and every operation on it fails deep inside the proactor with
    an error that looks nothing like its cause. NullPool opens and closes a
    connection per checkout, which removes the sharing entirely.

    This costs one connection setup per request, which is irrelevant in a test
    suite and would be unacceptable in production, hence the split.
    """
    if settings.environment == "ci":
        return {"poolclass": NullPool}
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
    }


async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.db_echo,
    **_async_engine_kwargs(),
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

sync_engine = create_engine(
    settings.sync_database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    The session is committed only by the caller. Any exception escaping the
    request handler rolls the transaction back before the connection returns to
    the pool, so a failed request can never leave partial writes behind.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@contextmanager
def sync_session() -> Iterator[Session]:
    """Context manager yielding a session for batch scripts and migrations."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
