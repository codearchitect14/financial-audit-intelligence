"""Schema-level integration tests.

These require a live Postgres. Start one with:

    docker compose -f infra/docker-compose.yml up -d db
    cd backend && uv run alembic upgrade head

They are skipped automatically when no database is reachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from fai.db.models import Organization, User, UserRole
from fai.db.session import sync_session

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _db(require_database: None) -> None:
    """Skip this whole module unless a database is available."""


class TestTimestampDefaults:
    """Regression guard for a real defect found during Phase 0.

    Declaring a column as ``server_default="now()"`` makes SQLAlchemy emit the
    value as a *literal*, which Postgres then coerces to a frozen constant:
    ``DEFAULT '2026-09-16 10:13:40+00'::timestamptz``. Every row inserted
    afterwards is stamped with the migration time rather than the insert time.

    On ``activity_log`` that silently destroys the audit trail while still
    looking correct in code review, so the invariant is asserted here rather
    than trusted.
    """

    def test_no_created_at_default_is_a_frozen_constant(self) -> None:
        with sync_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT table_name, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND column_name IN ('created_at', 'updated_at')
                    """
                )
            ).all()

        assert rows, "expected timestamp columns to exist; is the migration applied?"
        for table_name, column_default in rows:
            assert column_default == "now()", (
                f"{table_name}.created_at has default {column_default!r}. "
                "A literal timestamp here freezes every future row to the "
                "migration time. Use func.now(), not the string 'now()'."
            )

    def test_timestamps_advance_between_inserts(self) -> None:
        """The behavioural counterpart to the schema assertion above."""
        with sync_session() as session:
            first = Organization(name="Timestamp Probe A", slug=f"probe-a-{uuid.uuid4().hex[:8]}")
            session.add(first)
            session.flush()
            session.refresh(first)
            first_created = first.created_at

        with sync_session() as session:
            second = Organization(name="Timestamp Probe B", slug=f"probe-b-{uuid.uuid4().hex[:8]}")
            session.add(second)
            session.flush()
            session.refresh(second)
            second_created = second.created_at

        assert second_created > first_created
        assert (datetime.now(UTC) - second_created).total_seconds() < 60


class TestTenantIsolation:
    """The schema must make cross-tenant data structurally impossible to orphan."""

    def test_deleting_an_organization_removes_its_users(self) -> None:
        slug = f"cascade-{uuid.uuid4().hex[:8]}"
        with sync_session() as session:
            org = Organization(name="Cascade Test", slug=slug)
            session.add(org)
            session.flush()
            session.add(
                User(
                    organization_id=org.id,
                    email=f"{slug}@example.com",
                    hashed_password="not-a-real-hash",
                    full_name="Cascade Test User",
                    role=UserRole.VIEWER,
                )
            )
            org_id = org.id

        with sync_session() as session:
            session.delete(session.get(Organization, org_id))

        with sync_session() as session:
            remaining = session.execute(select(User).where(User.organization_id == org_id)).all()
        assert remaining == []


class TestVectorColumn:
    """The embedding column must match the configured model width exactly."""

    def test_embedding_width_matches_settings(self) -> None:
        from fai.core.config import settings

        with sync_session() as session:
            declared = session.execute(
                text(
                    """
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = 'document_chunks' AND a.attname = 'embedding'
                    """
                )
            ).scalar_one()

        assert declared == f"vector({settings.embedding_dimensions})"
