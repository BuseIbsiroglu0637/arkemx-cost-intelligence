
"""A3.6 - Non-persistent alternative cost scenario pilot.

Supports only the 15.275.1111 fine-mortar substitution.
The original PDF analysis must remain unchanged.
The alternative price requires independent source verification.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.technical_analysis.pdf_analysis_source import (
    EXPECTED_SHA256,
)

CENT = Decimal("0.01")

SOURCE_POSITION = "15.275.1111"
ORIGINAL_RESOURCE = "19.100.2508"
ALTERNATIVE_RESOURCE = "19.100.2506"

ORIGINAL_PRICE = Decimal("2054.48")
ALTERNATIVE_PRICE = Decimal("1926.15")
FIXED_QUANTITY = Decimal("0.010")


def _number(value: object) -> Decimal:
    """Accept finite decimal values, never floating-point inputs."""
    if isinstance(value, (float, bool)):
        raise ValueError("Floating-point or boolean input is forbidden")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid decimal value") from exc

    if not result.is_finite():
        raise ValueError("Non-finite decimal value")

    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_300kg_scenario(
    analysis: dict,
    *,
    alternative_code: str = ALTERNATIVE_RESOURCE,
    alternative_unit: str = "m³",
    alternative_unit_price: str = "1926.15",
) -> dict:
    """Calculate one explicitly constrained substitution.

    No database writes, engineering approval or source mutation.
    """

    if analysis.get("position_code") != SOURCE_POSITION:
        raise ValueError("Unsupported source position")

    if analysis.get("unit") != "m²":
        raise ValueError("Unexpected analysis unit")

    if (
        analysis.get("read_only") is not True
        or analysis.get("approval_allowed") is not False
    ):
        raise ValueError("Unsafe source record")

    source = analysis.get("source") or {}

    if (
        source.get("sha256") != EXPECTED_SHA256
        or source.get("pdf_page") != 423
        or source.get("price_date") != "2026-01-01"
    ):
        raise ValueError("Unverified original PDF identity")

    alternative_price = _number(alternative_unit_price)

    if (
        alternative_code != ALTERNATIVE_RESOURCE
        or alternative_unit != "m³"
        or alternative_price != ALTERNATIVE_PRICE
    ):
        raise ValueError("Unsupported alternative source fixture")

    resources = analysis.get("resources") or []

    original_rows = [
        row for row in resources
        if row.get("code") == ORIGINAL_RESOURCE
    ]

    if len(original_rows) != 1:
        raise ValueError("Original fine mortar row is not unique")

    original = original_rows[0]

    quantity = _number(original["quantity"])
    old_price = _number(original["unit_price"])
    old_amount = _number(original["amount"])

    if (
        original["unit"] != "m³"
        or quantity != FIXED_QUANTITY
        or old_price != ORIGINAL_PRICE
        or old_amount != _money(quantity * old_price)
    ):
        raise ValueError("Original resource does not match pilot")

    totals = analysis["totals"]

    subtotal = _number(totals["material_and_labor"])
    overhead = _number(totals["overhead_and_profit"])
    original_total = _number(totals["total"])
    rate = _number(totals["overhead_rate"])

    resource_sum = sum(
        (_number(row["amount"]) for row in resources),
        Decimal("0"),
    )

    if (
        subtotal != Decimal("595.60")
        or resource_sum != subtotal
        or rate != Decimal("0.25")
        or _money(subtotal * rate) != overhead
        or subtotal + overhead != original_total
        or original_total != Decimal("744.50")
    ):
        raise ValueError("Original analysis totals are inconsistent")

    # Only the fine mortar price changes.
    new_line_amount = _money(quantity * alternative_price)

    new_subtotal = _money(
        subtotal - old_amount + new_line_amount
    )

    # Overhead/profit is applied once to the new subtotal.
    new_overhead = _money(new_subtotal * rate)
    new_total = new_subtotal + new_overhead
    difference = new_total - original_total

    return {
        "schema": "arkemx.cost_scenario.v1",
        "read_only": True,
        "approval_allowed": False,
        "technical_compatibility": "not_evaluated",
        "alternative_price_verification": "pending_source_document",
        "source": {
            "position_code": SOURCE_POSITION,
            "sha256": source["sha256"],
            "pdf_page": 423,
            "price_date": source["price_date"],
        },
        "original": {
            "resource_code": ORIGINAL_RESOURCE,
            "resource_unit_price_tl": str(old_price),
            "resource_amount_tl": str(old_amount),
            "total_tl": str(original_total),
        },
        "replacement": {
            "resource_code": ALTERNATIVE_RESOURCE,
            "resource_unit": alternative_unit,
            "quantity": format(quantity, ".3f"),
            "unit_price_tl": str(alternative_price),
            "line_amount_tl": str(new_line_amount),
        },
        "scenario": {
            "subtotal_tl": str(new_subtotal),
            "overhead_tl": str(new_overhead),
            "total_tl": str(new_total),
            "difference_tl": str(difference),
            "unit": "m²",
        },
        "assumptions": {
            "quantity_fixed": True,
            "other_resources_unchanged": True,
            "overhead_rate": str(rate),
            "overhead_applied_once": True,
        },
    }
