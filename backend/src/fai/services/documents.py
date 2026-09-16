"""Document upload and storage.

Uploads are the most exposed write path in the application: the payload, its
name, and its declared type are all attacker-controlled. The rules below exist
because each has been a real vulnerability class in real systems.

* **The stored path is generated, never derived from the upload.** A filename
  such as ``../../../.env`` or ``C:\\Windows\\System32\\x`` must be unable to
  influence where bytes land. The original name is kept in a column, for
  display only.
* **Size is enforced while streaming, not from the Content-Length header.** A
  client can lie about the header, or send a chunked body with none at all.
* **Type is checked against an allowlist and verified against magic bytes.** The
  declared ``Content-Type`` is a claim by the uploader, not evidence.
* **Content is hashed and de-duplicated per tenant.** Re-uploading the same
  bytes reuses the existing row and its embeddings rather than paying to chunk
  and embed them twice.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.config import settings
from fai.core.errors import ValidationError
from fai.core.logging import get_logger
from fai.db.models import Document
from fai.db.models.enums import DocumentStatus, DocumentType

log = get_logger(__name__)

# Read in modest blocks so that a large upload never materialises in memory.
CHUNK_BYTES = 1 << 16

# Leading bytes that identify a format, checked against the declared type. This
# is not a complete content inspection, but it stops the simplest case: a
# payload renamed to .pdf and declared as application/pdf.
MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
}


def _safe_storage_path(organization_id: uuid.UUID, document_id: uuid.UUID, suffix: str) -> Path:
    """Build the storage path for an upload.

    Every component is generated. The only thing taken from the upload is the
    extension, and it is restricted to a short alphanumeric string, so it cannot
    contain a separator or a traversal sequence.
    """
    clean_suffix = "".join(c for c in suffix.lower() if c.isalnum())[:8]
    name = f"{document_id}.{clean_suffix}" if clean_suffix else str(document_id)
    # Sharded by organization so that one tenant's documents are never mixed
    # into another's directory, which makes a bulk export or deletion simple.
    return Path(str(organization_id)) / name


def _validate_declared_type(content_type: str) -> str:
    """Check the declared content type against the allowlist."""
    # Strip any parameters, for example "text/csv; charset=utf-8".
    base = content_type.split(";")[0].strip().lower()
    if base not in settings.allowed_upload_types:
        raise ValidationError(
            f"Unsupported file type {base!r}. Allowed: "
            f"{', '.join(sorted(settings.allowed_upload_types))}."
        )
    return base


def _verify_magic(content_type: str, head: bytes) -> None:
    """Verify the leading bytes are consistent with the declared type."""
    expected = MAGIC_PREFIXES.get(content_type)
    if expected and not any(head.startswith(prefix) for prefix in expected):
        raise ValidationError(f"File content does not match the declared type {content_type!r}.")


def store_upload(
    source: BinaryIO,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    content_type: str,
    filename: str,
    upload_root: Path | None = None,
    max_bytes: int | None = None,
) -> tuple[Path, int, str]:
    """Stream an upload to disk, enforcing the size cap as it goes.

    Returns the relative storage path, the byte count, and the SHA-256 digest.

    The size limit is checked against bytes actually read. Trusting
    Content-Length would let a client declare one byte and send a gigabyte.
    """
    root = upload_root or Path(settings.upload_dir)
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    relative = _safe_storage_path(organization_id, document_id, Path(filename).suffix.lstrip("."))
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    written = 0
    first_block = b""

    # Written under a temporary name and renamed only on success, so a rejected
    # or interrupted upload never leaves a file that looks complete.
    partial = destination.with_suffix(destination.suffix + ".partial")
    try:
        with partial.open("wb") as handle:
            while True:
                block = source.read(CHUNK_BYTES)
                if not block:
                    break
                if not first_block:
                    first_block = block
                    _verify_magic(content_type, first_block)

                written += len(block)
                if written > limit:
                    raise ValidationError(f"File exceeds the {limit // (1024 * 1024)}MB limit.")

                digest.update(block)
                handle.write(block)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    if written == 0:
        partial.unlink(missing_ok=True)
        raise ValidationError("The uploaded file is empty.")

    partial.replace(destination)
    return relative, written, digest.hexdigest()


async def find_duplicate(
    db: AsyncSession, *, organization_id: uuid.UUID, sha256: str
) -> Document | None:
    """Return an existing document with identical content, if any."""
    return (
        await db.execute(
            select(Document).where(
                Document.organization_id == organization_id,
                Document.sha256 == sha256,
            )
        )
    ).scalar_one_or_none()


async def create_document(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    file_path: Path,
    original_filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    doc_type: DocumentType,
) -> Document:
    """Record an uploaded document."""
    document = Document(
        organization_id=organization_id,
        uploaded_by=uploaded_by,
        file_path=str(file_path).replace("\\", "/"),
        # Bounded and stripped of any path component: this is display text and
        # must never be treated as a location.
        original_filename=Path(original_filename).name[:512],
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=sha256,
        doc_type=doc_type,
        status=DocumentStatus.UPLOADED,
    )
    db.add(document)
    await db.flush()
    return document


def validate_upload_headers(content_type: str | None, filename: str | None) -> tuple[str, str]:
    """Validate the parts of an upload known before the body is read."""
    if not filename:
        raise ValidationError("A filename is required.")
    if not content_type:
        raise ValidationError("A Content-Type is required.")
    return _validate_declared_type(content_type), filename
