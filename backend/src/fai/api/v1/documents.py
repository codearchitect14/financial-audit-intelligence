"""Document upload and listing endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy import func, select

from fai.api.deps import ClientIp, CurrentUserDep, DbSession, UploadRoot
from fai.core.errors import NotFoundError
from fai.core.rate_limit import limiter
from fai.db.models import Document, DocumentChunk
from fai.db.models.enums import DocumentType
from fai.schemas.common import Page, PageParams
from fai.schemas.finance import DocumentResponse
from fai.services import activity
from fai.services import documents as document_service

router = APIRouter(prefix="/documents", tags=["documents"])

Pagination = Annotated[PageParams, Depends()]


async def _with_chunk_count(db: DbSession, document: Document) -> DocumentResponse:
    count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
            )
        ).scalar_one()
    )
    response = DocumentResponse.model_validate(document)
    return response.model_copy(update={"chunk_count": count})


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
)
# Uploads consume storage and, downstream, embedding compute. Both are finite.
@limiter.limit("60/hour")
async def upload_document(
    request: Request,
    db: DbSession,
    current_user: CurrentUserDep,
    ip: ClientIp,
    upload_root: UploadRoot,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[DocumentType, Form()] = DocumentType.OTHER,
) -> DocumentResponse:
    """Accept a file, validate it, and store it for indexing.

    Re-uploading identical content returns the existing document rather than
    creating a duplicate, so the embedding cost is paid once.
    """
    current_user.require("documents:write")

    content_type, filename = document_service.validate_upload_headers(
        file.content_type, file.filename
    )

    document_id = uuid.uuid4()
    path, size, digest = document_service.store_upload(
        file.file,
        organization_id=current_user.organization_id,
        document_id=document_id,
        content_type=content_type,
        filename=filename,
        upload_root=upload_root,
    )

    existing = await document_service.find_duplicate(
        db, organization_id=current_user.organization_id, sha256=digest
    )
    if existing is not None:
        return await _with_chunk_count(db, existing)

    document = await document_service.create_document(
        db,
        organization_id=current_user.organization_id,
        uploaded_by=current_user.id,
        file_path=path,
        original_filename=filename,
        content_type=content_type,
        size_bytes=size,
        sha256=digest,
        doc_type=doc_type,
    )

    await activity.record(
        db,
        action=activity.ACTION_DOCUMENT_UPLOADED,
        resource_type="document",
        resource_id=document.id,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        detail={"filename": document.original_filename, "size_bytes": size},
        ip_address=ip,
    )
    await db.commit()
    await db.refresh(document)
    return await _with_chunk_count(db, document)


@router.get("", response_model=Page[DocumentResponse], summary="List uploaded documents")
async def list_documents(
    db: DbSession, current_user: CurrentUserDep, page: Pagination
) -> Page[DocumentResponse]:
    current_user.require("data:read")

    # Exact match, not the reference-data rule: documents are always private to
    # one organization and there is no public case.
    base = select(Document).where(Document.organization_id == current_user.organization_id)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (
        (
            await db.execute(
                base.order_by(Document.created_at.desc()).limit(page.limit).offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[DocumentResponse.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{document_id}", response_model=DocumentResponse, summary="Fetch one document")
async def get_document(
    document_id: uuid.UUID, db: DbSession, current_user: CurrentUserDep
) -> DocumentResponse:
    current_user.require("data:read")
    document = (
        await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("No such document.")
    return await _with_chunk_count(db, document)
