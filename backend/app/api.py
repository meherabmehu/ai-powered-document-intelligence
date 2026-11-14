import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from kombu.exceptions import OperationalError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai import create_embedding
from app.config import get_settings
from app.database import get_db
from app.models import Document, ProcessingAttempt
from app.processing import MEDIA_TYPES, SUPPORTED_EXTENSIONS
from app.schemas import (
    AttemptSummary,
    CorrectionRequest,
    DocumentDetail,
    DocumentSummary,
)
from app.tasks import _match_related_documents, _normalize_invoice, process_document_task
from app.validation import parse_amount, validate_invoice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
MAX_FILES_PER_UPLOAD = 10
UPLOAD_CHUNK_SIZE = 1024 * 1024
EXTRACTION_FIELDS = {
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
    "line_items",
    "uncertain_fields",
    "extraction_method",
}


def _literal_pattern(value: str) -> str:
    return f"%{value.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"


def _queue_processing(document_id: str) -> None:
    try:
        process_document_task.delay(document_id)
    except (OperationalError, OSError, ConnectionError) as exc:
        logger.error(
            "Could not enqueue document processing id=%s error=%s",
            document_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The processing queue is unavailable. The document was saved; retry it later.",
        ) from exc


@router.post("/documents/upload", response_model=list[DocumentSummary], status_code=202)
async def upload_documents(
    files: Annotated[list[UploadFile], File(...)],
    session: DbSession,
) -> list[Document]:
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one file to upload.")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"Upload no more than {MAX_FILES_PER_UPLOAD} files in one request.",
        )

    prepared: list[tuple[UploadFile, str, str]] = []
    for upload in files:
        filename = Path(upload.filename or "").name
        extension = Path(filename).suffix.lower()
        if not filename or extension not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type for {filename or 'unnamed file'}.",
            )
        safe_name = re.sub(r"[\x00-\x1f\x7f]", "", filename)[:255]
        prepared.append((upload, safe_name, extension))

    settings = get_settings()
    upload_dir = settings.upload_dir
    if not upload_dir.is_absolute():
        upload_dir = Path(__file__).resolve().parents[2] / upload_dir
    upload_dir = upload_dir.resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    created: list[Document] = []
    stored_paths: list[Path] = []
    try:
        for upload, filename, extension in prepared:
            document_id = str(uuid.uuid4())
            path = upload_dir / f"{document_id}{extension}"
            stored_paths.append(path)
            digest = hashlib.sha256()
            size = 0
            with path.open("wb") as target:
                while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"{filename} exceeds the {settings.max_upload_bytes}-byte limit.",
                        )
                    digest.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise HTTPException(status_code=400, detail=f"{filename} is empty.")

            created.append(
                Document(
                    id=document_id,
                    original_filename=filename,
                    media_type=MEDIA_TYPES[extension],
                    sha256=digest.hexdigest(),
                    size_bytes=size,
                    file_path=str(path),
                    status="queued",
                    progress=0,
                )
            )

        session.add_all(created)
        session.commit()
    except Exception:
        session.rollback()
        for path in stored_paths:
            path.unlink(missing_ok=True)
        raise
    finally:
        for upload in files:
            await upload.close()

    for document in created:
        try:
            _queue_processing(document.id)
        except HTTPException:
            document.status = "failed"
            document.progress = 100
            session.add(
                ProcessingAttempt(
                    document_id=document.id,
                    status="failed",
                    error_code="QUEUE_UNAVAILABLE",
                    error_message="The processing queue is unavailable. Retry this document later.",
                )
            )
            session.commit()
            logger.warning("Document saved but not queued id=%s", document.id)
    if any(document.status == "failed" for document in created):
        raise HTTPException(
            status_code=503,
            detail="One or more documents were saved but could not be queued. Retry them from the document list.",
        )
    return created


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    session: DbSession,
    document_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> list[Document]:
    query = select(Document)
    if document_status:
        if document_status not in {"queued", "processing", "completed", "failed"}:
            raise HTTPException(status_code=422, detail="Unsupported document status.")
        query = query.where(Document.status == document_status)
    return list(
        session.scalars(
            query.order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, session: DbSession) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/documents/{document_id}/status", response_model=DocumentSummary)
def get_document_status(document_id: str, session: DbSession) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/documents/{document_id}/result", response_model=DocumentDetail)
def get_document_result(document_id: str, session: DbSession) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Document results are not ready (status: {document.status}).",
        )
    return document


@router.get("/documents/{document_id}/attempts", response_model=list[AttemptSummary])
def list_document_attempts(
    document_id: str, session: DbSession
) -> list[ProcessingAttempt]:
    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return list(
        session.scalars(
            select(ProcessingAttempt)
            .where(ProcessingAttempt.document_id == document_id)
            .order_by(ProcessingAttempt.created_at.desc())
        ).all()
    )


@router.patch("/documents/{document_id}/correction", response_model=DocumentDetail)
def correct_document(
    document_id: str,
    correction: CorrectionRequest,
    session: DbSession,
) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.status != "completed" or document.extracted_data is None:
        raise HTTPException(status_code=409, detail="Only completed documents can be corrected.")

    unknown_fields = set(correction.extracted_data) - EXTRACTION_FIELDS
    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported invoice fields: {', '.join(sorted(unknown_fields))}.",
        )
    invoice = _normalize_invoice({**document.extracted_data, **correction.extracted_data})
    invoice["extraction_method"] = "manual-correction"
    is_duplicate, mismatched_ids = _match_related_documents(session, document, invoice)
    issues = validate_invoice(
        invoice,
        duplicate_invoice=is_duplicate and not mismatched_ids,
        similar_documents=mismatched_ids,
    )
    document.extracted_data = invoice
    document.validation_issues = issues
    document.invoice_number = invoice["invoice_number"]
    document.supplier_name = invoice["supplier_name"]
    document.invoice_total = parse_amount(invoice["total"])
    session.commit()
    session.refresh(document)
    return document


@router.post(
    "/documents/{document_id}/retry", response_model=DocumentSummary, status_code=202
)
def retry_document(document_id: str, session: DbSession) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed documents can be retried.")
    document.status = "queued"
    document.progress = 0
    session.commit()
    try:
        _queue_processing(document.id)
    except HTTPException:
        document.status = "failed"
        document.progress = 100
        session.add(
            ProcessingAttempt(
                document_id=document.id,
                status="failed",
                error_code="QUEUE_UNAVAILABLE",
                error_message="The processing queue is unavailable. Retry this document later.",
            )
        )
        session.commit()
        raise
    return document


@router.get("/search", response_model=list[DocumentSummary])
async def search_documents(
    session: DbSession,
    q: str = Query(min_length=1, max_length=500),
    mode: Literal["keyword", "semantic"] = "keyword",
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Document]:
    if mode == "keyword":
        pattern = _literal_pattern(q)
        return list(
            session.scalars(
                select(Document)
                .where(
                    or_(
                        Document.original_filename.ilike(pattern, escape="!"),
                        Document.extracted_text.ilike(pattern, escape="!"),
                        Document.invoice_number.ilike(pattern, escape="!"),
                        Document.supplier_name.ilike(pattern, escape="!"),
                    )
                )
                .order_by(Document.created_at.desc())
                .limit(limit)
            ).all()
        )

    try:
        vector = await create_embedding(q)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Semantic search embedding failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not create a search embedding.") from exc
    if vector is None:
        raise HTTPException(
            status_code=503,
            detail="Semantic search is unavailable; configure an embedding provider.",
        )
    distance = Document.embedding.cosine_distance(vector)
    return list(
        session.scalars(
            select(Document)
            .where(Document.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        ).all()
    )
