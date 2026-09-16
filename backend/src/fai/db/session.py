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

from fai.core.config import settings

async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
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
