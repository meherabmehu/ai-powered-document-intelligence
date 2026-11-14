from decimal import Decimal, InvalidOperation
from typing import Any

REQUIRED_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)


def parse_amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("৳", "").strip())
    except (InvalidOperation, ValueError):
        return None


def validate_invoice(
    invoice: dict[str, Any],
    *,
    duplicate_invoice: bool = False,
    similar_documents: list[str] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    for field in REQUIRED_FIELDS:
        if invoice.get(field) in (None, ""):
            issues.append(
                {
                    "code": "MISSING_FIELD",
                    "severity": "review",
                    "field": field,
                    "message": f"{field.replace('_', ' ').capitalize()} is missing.",
                }
            )

    amounts: dict[str, Decimal] = {}
    for field in ("subtotal", "tax", "total"):
        value = invoice.get(field)
        if value not in (None, ""):
            parsed = parse_amount(value)
            if parsed is None:
                issues.append(
                    {
                        "code": "INVALID_AMOUNT",
                        "severity": "error",
                        "field": field,
                        "message": f"{field.replace('_', ' ').capitalize()} is not a valid number.",
                    }
                )
            elif parsed < 0:
                issues.append(
                    {
                        "code": "NEGATIVE_AMOUNT",
                        "severity": "error",
                        "field": field,
                        "message": f"{field.replace('_', ' ').capitalize()} cannot be negative.",
                    }
                )
            else:
                amounts[field] = parsed

    subtotal = amounts.get("subtotal")
    tax = amounts.get("tax")
    total = amounts.get("total")
    if (
        subtotal is not None
        and tax is not None
        and total is not None
        and abs(subtotal + tax - total) > Decimal("0.02")
    ):
        issues.append(
            {
                "code": "TOTAL_MISMATCH",
                "severity": "error",
                "field": "total",
                "message": "Subtotal plus tax does not match the invoice total.",
            }
        )

    line_items = invoice.get("line_items") or []
    line_amounts: list[Decimal | None] = []
    for index, item in enumerate(line_items):
        if not isinstance(item, dict):
            continue
        amount_value = item.get("amount")
        amount = parse_amount(amount_value)
        if amount_value not in (None, "") and amount is None:
            issues.append(
                {
                    "code": "INVALID_LINE_ITEM_AMOUNT",
                    "severity": "error",
                    "field": f"line_items[{index}].amount",
                    "message": "Line-item amount is not a valid number.",
                }
            )
        line_amounts.append(amount)
        quantity = parse_amount(item.get("quantity"))
        unit_price = parse_amount(item.get("unit_price"))
        if (
            quantity is not None
            and unit_price is not None
            and amount is not None
            and abs(quantity * unit_price - amount) > Decimal("0.02")
        ):
            issues.append(
                {
                    "code": "LINE_ITEM_ARITHMETIC_MISMATCH",
                    "severity": "review",
                    "field": f"line_items[{index}]",
                    "message": "Quantity multiplied by unit price does not match line-item amount.",
                }
            )
    if (
        subtotal is not None
        and line_amounts
        and all(value is not None for value in line_amounts)
        and abs(sum(value for value in line_amounts if value is not None) - subtotal)
        > Decimal("0.02")
    ):
        issues.append(
            {
                "code": "LINE_ITEMS_MISMATCH",
                "severity": "review",
                "field": "line_items",
                "message": "The sum of line-item amounts does not match the subtotal.",
            }
        )

    if duplicate_invoice:
        issues.append(
            {
                "code": "DUPLICATE_INVOICE",
                "severity": "review",
                "field": "invoice_number",
                "message": "An invoice with the same supplier and invoice number already exists.",
            }
        )

    for document_id in similar_documents or []:
        issues.append(
            {
                "code": "CROSS_DOCUMENT_MISMATCH",
                "severity": "review",
                "field": "total",
                "message": f"Invoice details disagree with related document {document_id}.",
            }
        )

    return issues
