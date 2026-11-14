import asyncio
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from app.ai import create_embedding, extract_invoice_with_llm
from app.database import SessionLocal
from app.models import Document, ProcessingAttempt
from app.processing import DocumentProcessingError, extract_document, extract_invoice_fields
from app.queue import celery_app
from app.validation import parse_amount, validate_invoice

logger = logging.getLogger(__name__)

INVOICE_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)


def _normalize_invoice(payload: dict[str, Any]) -> dict[str, Any]:
    invoice = {field: payload.get(field) for field in INVOICE_FIELDS}
    for field in INVOICE_FIELDS:
        value = invoice[field]
        if isinstance(value, str) and value.strip().casefold() in {
            "",
            "null",
            "unknown",
            "not provided",
            "n/a",
        }:
            invoice[field] = None
    invoice["line_items"] = payload.get("line_items") or []
    invoice["uncertain_fields"] = payload.get("uncertain_fields") or []
    invoice["extraction_method"] = payload.get("extraction_method", "local-patterns")
    return invoice


def _match_related_documents(
    session: Any, document: Document, invoice: dict[str, Any]
) -> tuple[bool, list[str]]:
    invoice_number = invoice.get("invoice_number")
    supplier = invoice.get("supplier_name")
    if not invoice_number or not supplier:
        return False, []
    siblings = session.scalars(
        select(Document).where(
            Document.status == "completed",
            Document.id != document.id,
            func.lower(Document.invoice_number) == str(invoice_number).strip().lower(),
            func.lower(Document.supplier_name) == str(supplier).strip().lower(),
        )
    ).all()
    if not siblings:
        return False, []

    current_total = parse_amount(invoice.get("total"))
    mismatched: list[str] = []
    for sibling in siblings:
        sibling_total = parse_amount(sibling.invoice_total)
        if current_total is not None and sibling_total is not None and abs(current_total - sibling_total) > Decimal("0.02"):
            mismatched.append(sibling.id)
    return True, mismatched


@celery_app.task(name="app.tasks.process_document", bind=True)
def process_document_task(self: Any, document_id: str) -> dict[str, str]:
    started = time.monotonic()
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("Processing job references missing document id=%s", document_id)
            return {"status": "missing", "document_id": document_id}

        document.status = "processing"
        document.progress = 5
        attempt = ProcessingAttempt(document_id=document.id, status="processing")
        session.add(attempt)
        session.commit()

        try:
            content = extract_document(Path(document.file_path))
            document.progress = 45
            session.commit()

            local_invoice = extract_invoice_fields(content.text, content.spreadsheet_sheets)
            invoice = local_invoice
            extraction_issue: dict[str, str] | None = None
            try:
                llm_invoice = asyncio.run(extract_invoice_with_llm(content.text))
                if llm_invoice is not None:
                    invoice = llm_invoice
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                logger.warning("LLM extraction failed for document id=%s: %s", document.id, type(exc).__name__)
                extraction_issue = {
                    "code": "AI_EXTRACTION_UNAVAILABLE",
                    "severity": "review",
                    "field": "extracted_data",
                    "message": "AI extraction was unavailable; review the local extraction before use.",
                }

            invoice = _normalize_invoice(invoice)
            document.progress = 70
            session.commit()

            is_duplicate, mismatched_ids = _match_related_documents(session, document, invoice)
            issues = validate_invoice(
                invoice,
                duplicate_invoice=is_duplicate and not mismatched_ids,
                similar_documents=mismatched_ids,
            )
            if extraction_issue:
                issues.append(extraction_issue)
            if invoice["uncertain_fields"]:
                issues.append(
                    {
                        "code": "UNCERTAIN_EXTRACTION",
                        "severity": "review",
                        "field": "extracted_data",
                        "message": "One or more extracted fields are uncertain and need manual review.",
                    }
                )

            embedding: list[float] | None = None
            try:
                embedding = asyncio.run(create_embedding(content.text))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("Embedding request failed for document id=%s: %s", document.id, type(exc).__name__)
                issues.append(
                    {
                        "code": "EMBEDDING_UNAVAILABLE",
                        "severity": "review",
                        "field": "search",
                        "message": "Semantic search indexing failed; keyword search remains available.",
                    }
                )

            document.extracted_text = content.text
            document.extracted_data = invoice
            document.validation_issues = issues
            document.invoice_number = invoice["invoice_number"]
            document.supplier_name = invoice["supplier_name"]
            document.invoice_total = parse_amount(invoice["total"])
            document.embedding = embedding
            document.status = "completed"
            document.progress = 100
            attempt.status = "completed"
            attempt.duration_ms = round((time.monotonic() - started) * 1000)
            session.commit()
            return {"status": "completed", "document_id": document.id}

        except DocumentProcessingError as exc:
            document.status = "failed"
            document.progress = 100
            attempt.status = "failed"
            attempt.error_code = exc.code
            attempt.error_message = str(exc)
            attempt.duration_ms = round((time.monotonic() - started) * 1000)
            session.commit()
            logger.info("Document processing failed id=%s code=%s", document.id, exc.code)
            return {"status": "failed", "document_id": document.id, "error_code": exc.code}
        except (OSError, ValueError) as exc:
            document.status = "failed"
            document.progress = 100
            attempt.status = "failed"
            attempt.error_code = "PROCESSING_ERROR"
            attempt.error_message = "Processing failed. Check the file and configured providers, then retry."
            attempt.duration_ms = round((time.monotonic() - started) * 1000)
            session.commit()
            logger.exception("Document processing failed id=%s", document.id, exc_info=exc)
            return {"status": "failed", "document_id": document.id, "error_code": "PROCESSING_ERROR"}
