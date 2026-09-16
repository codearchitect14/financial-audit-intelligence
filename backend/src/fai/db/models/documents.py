"""Uploaded documents and their embedded chunks (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fai.core.config import settings
from fai.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fai.db.models.enums import DocumentStatus, DocumentType

if TYPE_CHECKING:
    from fai.db.models.tenancy import Organization, User


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file uploaded by a tenant.

    Always private to one organization: unlike companies and statements there
    is no public-reference case, so ``organization_id`` is NOT NULL.
    """

    __tablename__ = "documents"
    __table_args__ = (
        # Content-addressed de-duplication within a tenant. Re-uploading the
        # same bytes reuses the existing row and its embeddings rather than
        # paying to chunk and embed it twice.
        UniqueConstraint("organization_id", "sha256", name="uq_document_org_sha256"),
        Index("ix_documents_organization_id_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Storage key, relative to the configured upload root or bucket prefix.
    # Never an absolute path from the uploader, and never the original
    # filename: both are attacker-controlled and invite path traversal.
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    doc_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False, length=32),
        nullable=False,
        default=DocumentType.OTHER,
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, native_enum=False, length=32),
        nullable=False,
        default=DocumentStatus.UPLOADED,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[Organization] = relationship()
    uploader: Mapped[User | None] = relationship(back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(UUIDPrimaryKeyMixin, Base):
    """A passage of a document together with its embedding vector.

    The vector width is pinned to ``settings.embedding_dimensions`` (384, for
    ``BAAI/bge-small-en-v1.5``). Changing the embedding model to one with a
    different width requires a migration and a full re-embed; the startup check
    in ``fai.main`` refuses to boot on a mismatch rather than writing vectors
    the index cannot use.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the parent document so that similarity search can
    # filter by tenant without joining, which matters once the index is in use.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
