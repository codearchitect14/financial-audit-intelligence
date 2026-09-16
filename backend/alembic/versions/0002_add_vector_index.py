"""Add the HNSW index for vector similarity search.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # HNSW rather than IVFFlat. IVFFlat must be built against existing data to
    # form its clusters, so it cannot usefully be created on an empty table and
    # degrades as the distribution shifts. HNSW builds incrementally, gives
    # better recall at the same speed, and needs no retraining.
    #
    # vector_cosine_ops matches the operator used by the search query. An index
    # built for a different metric is silently ignored by the planner, which
    # looks exactly like "pgvector is slow" rather than like a mistake.
    #
    # m=16, ef_construction=64 are the pgvector defaults: a reasonable
    # recall/build-time balance for a corpus of this size. Raising
    # ef_construction improves recall at the cost of a slower build.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # Every search filters by organization before ranking. Without this the
    # planner has to choose between the vector index and the tenant filter;
    # with it, the tenant filter is cheap enough to apply either way.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_org_document
        ON document_chunks (organization_id, document_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_org_document")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
