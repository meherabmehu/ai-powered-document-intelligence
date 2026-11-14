import io
import logging
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import pandas as pd
import pymupdf
import pytesseract
from PIL import Image, ImageSequence, UnidentifiedImageError

from app.config import get_settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".xlsx", ".xls", ".csv"}
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
}


class DocumentProcessingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProcessedContent:
    text: str
    source_kind: str
    spreadsheet_sheets: dict[str, list[dict[str, Any]]]
    ocr_pages: int
    page_count: int


def _validate_signature(path: Path, extension: str) -> None:
    try:
        with path.open("rb") as file:
            header = file.read(8)
    except OSError as exc:
        raise DocumentProcessingError("FILE_READ_ERROR", "Could not read the uploaded file.") from exc

    signatures = {
        ".pdf": header.startswith(b"%PDF-"),
        ".jpg": header.startswith(b"\xff\xd8\xff"),
        ".jpeg": header.startswith(b"\xff\xd8\xff"),
        ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        ".tif": header.startswith((b"II*\x00", b"MM\x00*")),
        ".tiff": header.startswith((b"II*\x00", b"MM\x00*")),
        ".xlsx": header.startswith(b"PK\x03\x04"),
        ".xls": header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        ".csv": True,
    }
    if extension not in signatures or not signatures[extension]:
        raise DocumentProcessingError("INVALID_FILE_SIGNATURE", "File contents do not match the file type.")

    if extension == ".csv":
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                sample = file.read(8192)
            if not sample.strip():
                raise DocumentProcessingError("EMPTY_FILE", "The CSV file is empty.")
        except UnicodeDecodeError as exc:
            raise DocumentProcessingError("INVALID_CSV", "The CSV file could not be decoded or parsed.") from exc


def _run_ocr(image: Image.Image) -> str:
    settings = get_settings()
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        return pytesseract.image_to_string(image, timeout=60).strip()
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, RuntimeError) as exc:
        raise DocumentProcessingError(
            "OCR_UNAVAILABLE", "OCR failed. Install Tesseract and confirm its configured path."
        ) from exc


def _extract_pdf(path: Path) -> ProcessedContent:
    try:
        document = pymupdf.open(path)
    except (pymupdf.FileDataError, OSError) as exc:
        raise DocumentProcessingError("CORRUPT_PDF", "The PDF file is corrupted or unreadable.") from exc

    settings = get_settings()
    if document.page_count > settings.max_pdf_pages:
        document.close()
        raise DocumentProcessingError("PAGE_LIMIT_EXCEEDED", "PDF exceeds the configured page limit.")

    text_parts: list[str] = []
    ocr_pages = 0
    try:
        for page_number, page in enumerate(document, start=1):
            page_text = page.get_text("text").strip()
            if len(page_text) < 20:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                page_text = _run_ocr(image)
                ocr_pages += 1
            text_parts.append(f"[Page {page_number}]\n{page_text}")
    finally:
        document.close()
    return ProcessedContent("\n\n".join(text_parts), "pdf", {}, ocr_pages, len(text_parts))


def _extract_image(path: Path) -> ProcessedContent:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                page_texts: list[str] = []
                for index, frame in enumerate(ImageSequence.Iterator(image), start=1):
                    if index > get_settings().max_pdf_pages:
                        raise DocumentProcessingError(
                            "PAGE_LIMIT_EXCEEDED",
                            "Image has more pages than the configured limit.",
                        )
                    page_texts.append(f"[Image page {index}]\n{_run_ocr(frame.convert('RGB'))}")
    except DocumentProcessingError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise DocumentProcessingError("CORRUPT_IMAGE", "The image file is corrupted or unreadable.") from exc
    return ProcessedContent("\n\n".join(page_texts), "image", {}, len(page_texts), len(page_texts))


def _extract_spreadsheet(path: Path, extension: str) -> ProcessedContent:
    try:
        if extension == ".csv":
            frames = {"CSV": pd.read_csv(path, dtype=object, keep_default_na=False)}
        else:
            with pd.ExcelFile(path) as excel:
                frames = {
                    sheet_name: excel.parse(sheet_name, dtype=object, keep_default_na=False)
                    for sheet_name in excel.sheet_names
                }
    except (
        BadZipFile,
        OSError,
        ValueError,
        ImportError,
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
    ) as exc:
        raise DocumentProcessingError(
            "CORRUPT_SPREADSHEET", "The spreadsheet file is corrupted or could not be parsed."
        ) from exc

    sheets: dict[str, list[dict[str, Any]]] = {}
    text_parts: list[str] = []
    for sheet_name, frame in frames.items():
        records = frame.fillna("").to_dict(orient="records")
        sheets[sheet_name] = [
            {str(key): _clean_cell(value) for key, value in row.items()} for row in records
        ]
        text_parts.append(f"[Sheet: {sheet_name}]\n{frame.to_string(index=False, na_rep='')}")
    return ProcessedContent("\n\n".join(text_parts), "spreadsheet", sheets, 0, len(sheets))


def _clean_cell(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not pd.notna(value):
        return None
    return value


def extract_document(path: Path) -> ProcessedContent:
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentProcessingError("UNSUPPORTED_FILE_TYPE", "This file type is not supported.")
    _validate_signature(path, extension)
    if extension == ".pdf":
        return _extract_pdf(path)
    if extension in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        return _extract_image(path)
    return _extract_spreadsheet(path, extension)


def extract_invoice_fields(text: str, spreadsheet_sheets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Conservative local extraction; fields not explicitly found remain null."""
    patterns = {
        "invoice_number": r"(?im)^\s*(?:invoice\s*(?:number|no\.?|#)|inv\.?\s*#?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]+)",
        "invoice_date": r"(?im)^\s*(?:invoice\s*date|date)\s*[:#-]?\s*([0-9]{1,4}[./-][0-9]{1,2}[./-][0-9]{1,4})",
        "supplier_name": r"(?im)^\s*(?:supplier|vendor|from)\s*[:#-]\s*(.+?)\s*$",
        "customer_name": r"(?im)^\s*(?:customer|bill\s*to|sold\s*to)\s*[:#-]\s*(.+?)\s*$",
        "currency": r"(?i)\b(USD|EUR|GBP|CAD|AUD|BDT|INR|JPY|৳|\$|€|£)\b",
    }
    fields: dict[str, Any] = {
        "invoice_number": None,
        "invoice_date": None,
        "supplier_name": None,
        "customer_name": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "currency": None,
        "line_items": [],
        "uncertain_fields": [],
        "extraction_method": "local-patterns",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            fields[field] = match.group(1).strip()

    for field, label in (("subtotal", r"sub\s*total"), ("tax", r"(?:tax|vat|gst)"), ("total", r"(?:grand\s+total|amount\s+due|total)")):
        match = re.search(
            rf"(?im)^\s*{label}\s*[:#-]?\s*(?:[A-Z]{{3}}\s*)?[$€£৳]?\s*([-+]?\d[\d,]*(?:\.\d{{1,4}})?)",
            text,
        )
        if match:
            fields[field] = match.group(1).replace(",", "")

    if spreadsheet_sheets:
        rows = [row for sheet in spreadsheet_sheets.values() for row in sheet]
        fields["line_items"] = rows[:500]
    else:
        fields["line_items"] = _extract_line_items(text)

    return fields


def _extract_line_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    row_pattern = re.compile(
        r"^\s*(.+?)\s{2,}(\d+(?:\.\d+)?)\s+([$€£৳]?\s*[\d,]+(?:\.\d{1,2})?)\s*$"
    )
    for line in text.splitlines():
        match = row_pattern.match(line)
        if match:
            items.append(
                {
                    "description": match.group(1).strip(),
                    "quantity": match.group(2),
                    "amount": re.sub(r"[^\d.-]", "", match.group(3)),
                }
            )
    return items
