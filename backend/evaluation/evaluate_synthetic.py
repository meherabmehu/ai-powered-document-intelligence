import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.processing import extract_invoice_fields
from app.validation import validate_invoice

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "synthetic_invoices.jsonl"
EVALUATED_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)


def _equal(field: str, actual: Any, expected: Any) -> bool:
    if field in {"subtotal", "tax", "total"}:
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except (InvalidOperation, ValueError):
            return False
    return str(actual or "").strip().casefold() == str(expected or "").strip().casefold()


def main() -> None:
    samples = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    totals = {field: 0 for field in EVALUATED_FIELDS}
    correct = {field: 0 for field in EVALUATED_FIELDS}
    validation_issue_count = 0
    for sample in samples:
        actual = extract_invoice_fields(sample["text"], {})
        for field in EVALUATED_FIELDS:
            totals[field] += 1
            correct[field] += _equal(field, actual.get(field), sample["expected"].get(field))
        validation_issue_count += len(validate_invoice(actual))

    field_accuracy = {
        field: round(correct[field] / totals[field], 4) if totals[field] else 0
        for field in EVALUATED_FIELDS
    }
    overall = sum(correct.values()) / sum(totals.values()) if totals else 0
    print(
        json.dumps(
            {
                "dataset": DATASET.name,
                "dataset_type": "synthetic demonstration data; not a real-world benchmark",
                "sample_count": len(samples),
                "field_count": len(EVALUATED_FIELDS),
                "correct_fields": sum(correct.values()),
                "total_fields": sum(totals.values()),
                "micro_exact_match_accuracy": round(overall, 4),
                "per_field_exact_match_accuracy": field_accuracy,
                "validation_issues_across_samples": validation_issue_count,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
