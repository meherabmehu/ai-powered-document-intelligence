from pathlib import Path

import pymupdf
import pytest

from app import processing
from app.processing import (
    DocumentProcessingError,
    extract_document,
    extract_invoice_fields,
)
from app.tasks import _normalize_invoice
from app.validation import validate_invoice


def test_local_invoice_extraction_keeps_missing_values_unknown() -> None:
    invoice = extract_invoice_fields(
        "Invoice Number: INV-42\n"
        "Supplier: Northwind Supplies\n"
        "Subtotal: $100.00\nTax: $5.00\nTotal: $105.00",
        {},
    )

    assert invoice["invoice_number"] == "INV-42"
    assert invoice["supplier_name"] == "Northwind Supplies"
    assert invoice["subtotal"] == "100.00"
    assert invoice["total"] == "105.00"
    assert invoice["invoice_date"] is None
    assert invoice["customer_name"] is None


def test_normalization_does_not_turn_placeholder_strings_into_values() -> None:
    invoice = _normalize_invoice({"invoice_number": "unknown", "total": "105.00"})

    assert invoice["invoice_number"] is None
    assert invoice["total"] == "105.00"
    assert invoice["supplier_name"] is None


def test_validation_detects_amount_mismatch_and_duplicate() -> None:
    issues = validate_invoice(
        {
            "invoice_number": "INV-42",
            "invoice_date": "2025-01-01",
            "supplier_name": "Northwind Supplies",
            "customer_name": "Example Customer",
            "subtotal": "100.00",
            "tax": "5.00",
            "total": "110.00",
            "currency": "USD",
        },
        duplicate_invoice=True,
    )

    codes = {issue["code"] for issue in issues}
    assert "TOTAL_MISMATCH" in codes
    assert "DUPLICATE_INVOICE" in codes


def test_unsupported_content_fails_with_a_specific_error(tmp_path: Path) -> None:
    path = tmp_path / "not-a-document.exe"
    path.write_bytes(b"not a supported document")

    with pytest.raises(DocumentProcessingError) as error:
        extract_document(path)

    assert error.value.code == "UNSUPPORTED_FILE_TYPE"


def test_pdf_text_is_extracted_without_ocr(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Invoice Number: INV-2025-001 with enough searchable text")
    pdf.save(path)
    pdf.close()

    content = extract_document(path)

    assert content.source_kind == "pdf"
    assert content.ocr_pages == 0
    assert "INV-2025-001" in content.text


def test_csv_is_preserved_as_sheet_rows(tmp_path: Path) -> None:
    path = tmp_path / "invoice.csv"
    path.write_text("description,quantity,amount\nCare visit,2,100.00\n", encoding="utf-8")

    content = extract_document(path)

    assert content.spreadsheet_sheets["CSV"][0]["description"] == "Care visit"
    assert "100.00" in content.text


def test_single_column_csv_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "notes.csv"
    path.write_text("memo\nA single field\n", encoding="utf-8")

    content = extract_document(path)

    assert content.spreadsheet_sheets["CSV"][0]["memo"] == "A single field"


def test_image_uses_ocr_and_respects_frame_flow(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    path = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(path)
    monkeypatch.setattr(processing, "_run_ocr", lambda _image: "recognized invoice text")

    content = extract_document(path)

    assert content.source_kind == "image"
    assert content.ocr_pages == 1
    assert "recognized invoice text" in content.text


def test_image_frame_limit_is_enforced(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    path = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(path)
    monkeypatch.setattr(processing.get_settings(), "max_pdf_pages", 0)

    with pytest.raises(DocumentProcessingError) as error:
        extract_document(path)

    assert error.value.code == "PAGE_LIMIT_EXCEEDED"


def test_pdf_extension_with_wrong_signature_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"not a pdf")

    with pytest.raises(DocumentProcessingError) as error:
        extract_document(path)

    assert error.value.code == "INVALID_FILE_SIGNATURE"


def test_line_item_arithmetic_is_checked() -> None:
    issues = validate_invoice(
        {
            "invoice_number": "INV-1",
            "invoice_date": "2025-01-01",
            "supplier_name": "Supplier",
            "customer_name": "Customer",
            "subtotal": "20.00",
            "tax": "0.00",
            "total": "20.00",
            "currency": "USD",
            "line_items": [{"quantity": "2", "unit_price": "10.00", "amount": "18.00"}],
        }
    )

    assert "LINE_ITEM_ARITHMETIC_MISMATCH" in {issue["code"] for issue in issues}
