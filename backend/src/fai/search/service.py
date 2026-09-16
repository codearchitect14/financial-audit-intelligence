"""Indexing and similarity search over document chunks.

Search here is pure vector retrieval: an embedding, a pgvector distance
operator, and an ordered result set. **No LLM is involved.** The ``/search``
endpoint returns passages, not answers, which is what keeps it free to run and
instant to respond. The LLM only enters in Phase 5, when a user asks for those
passages to be turned into an answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from fai.core.config import settings
from fai.core.logging import get_logger
from fai.db.models import Document, DocumentChunk
from fai.db.models.enums import DocumentStatus
from fai.search.embeddings import Embedder, batched, chunk_text, get_embedder

log = get_logger(__name__)

# Chunks embedded per forward pass. Larger batches are faster but hold more
# activations in memory, and the deployment target has very little.
EMBED_BATCH = 32


@dataclass(frozen=True)
class SearchHit:
    """One retrieved passage."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    chunk_index: int
    text: str
    # Cosine similarity in 0-1, where 1 is identical. Converted from pgvector's
    # cosine *distance* so that the API exposes the direction users expect:
    # a higher number is a better match.
    similarity: float


def extract_text(path: Path, content_type: str) -> str:
    """Read the text content of a stored document.

    PDF extraction is deliberately not implemented here. Doing it properly
    needs a parser with its own security surface, and shipping a silently
    empty extraction would be worse than an explicit gap: the document would
    index as zero chunks and simply never appear in results.
    """
    if content_type in ("text/plain", "text/csv"):
        return path.read_text(encoding="utf-8", errors="replace")
    if content_type == "application/pdf":
        raise NotImplementedError(
            "PDF text extraction is not yet implemented. Upload the extracted text "
            "as text/plain, or add a PDF parser before indexing PDFs."
        )
    raise ValueError(f"Cannot extract text from content type {content_type!r}.")


def index_document(
    session: Session,
    document: Document,
    text: str,
    *,
    embedder: Embedder | None = None,
) -> int:
    """Chunk, embed, and store a document's passages.

    Existing chunks are deleted first, so re-indexing after a chunking change
    replaces cleanly rather than leaving two overlapping generations of vectors
    that both match the same query.
    """
    embedder = embedder or get_embedder()

    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))

    chunks = chunk_text(text)
    if not chunks:
        document.status = DocumentStatus.INDEXED
        return 0

    document.status = DocumentStatus.EMBEDDING
    session.flush()

    written = 0
    for offset, batch in enumerate(batched(chunks, EMBED_BATCH)):
        vectors = embedder.embed(batch)
        for position, (passage, vector) in enumerate(zip(batch, vectors, strict=True)):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    organization_id=document.organization_id,
                    chunk_index=offset * EMBED_BATCH + position,
                    chunk_text=passage,
                    token_count=len(passage) // 4,
                    embedding=vector,
                )
            )
            written += 1

    document.status = DocumentStatus.INDEXED
    session.flush()

    log.info("document_indexed", document_id=str(document.id), chunks=written)
    return written


async def search(
    db: AsyncSession,
    query: str,
    *,
    organization_id: uuid.UUID,
    limit: int = 10,
    document_id: uuid.UUID | None = None,
    embedder: Embedder | None = None,
) -> Sequence[SearchHit]:
    """Find the passages most similar to a query.

    Always filtered by organization. Chunks carry a denormalised
    ``organization_id`` precisely so this filter costs no join and can never be
    accidentally omitted by a query planner decision.
    """
    if not query.strip():
        return []

    embedder = embedder or get_embedder()
    vector = embedder.embed_query(query)

    # Cosine distance. The vectors are normalised, so cosine is the correct
    # metric and the index below is built for the matching operator class.
    distance = DocumentChunk.embedding.cosine_distance(vector)

    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.chunk_text,
            Document.original_filename,
            distance.label("distance"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.embedding.isnot(None),
        )
        .order_by(distance)
        .limit(limit)
    )

    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)

    rows = (await db.execute(statement)).all()

    return [
        SearchHit(
            chunk_id=row.id,
            document_id=row.document_id,
            document_name=row.original_filename,
            chunk_index=row.chunk_index,
            text=row.chunk_text,
            # pgvector returns distance, where lower is better. The API exposes
            # similarity, where higher is better, because every user who reads
            # a score expects that direction.
            similarity=round(1.0 - float(row.distance), 6),
        )
        for row in rows
    ]


async def index_pending_documents(
    session: Session, *, embedder: Embedder | None = None, limit: int = 50
) -> int:
    """Index every document that has been uploaded but not yet embedded."""
    documents = (
        session.execute(
            select(Document).where(Document.status == DocumentStatus.UPLOADED).limit(limit)
        )
        .scalars()
        .all()
    )

    total = 0
    root = Path(settings.upload_dir)
    for document in documents:
        try:
            text = extract_text(root / document.file_path, document.content_type)
        except (NotImplementedError, ValueError, OSError) as exc:
            # A document that cannot be read is recorded as failed, with the
            # reason. Leaving it in "uploaded" would make the indexer retry it
            # forever on every run.
            document.status = DocumentStatus.FAILED
            document.error = str(exc)[:500]
            log.warning("document_index_failed", document_id=str(document.id), error=str(exc))
            continue

        total += index_document(session, document, text, embedder=embedder)

    session.flush()
    return total
