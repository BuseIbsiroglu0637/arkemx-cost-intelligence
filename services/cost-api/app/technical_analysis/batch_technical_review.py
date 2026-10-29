"""Bounded, read-only pilot over existing metraj rows and explicit candidates.

No candidate search, engineering approval, cost scenario or database writes.
"""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.excel import normalize_unit
from app.technical_analysis.comparator import compare_layers
from app.technical_analysis.pdf_analysis_source import read_analysis
from app.technical_analysis.support_registry import get_position_support

MAX_PILOT_ROWS = 20


@dataclass(frozen=True)
class PilotRow:
    work_item_id: str
    import_id: str
    sheet_name: str
    source_row: int
    original_description: str
    description: str
    quantity: str | None
    unit: str | None
    candidate_code: str | None
    revision_id: str | None = None
    input_review_required: bool = False


def row_from_effective_item(
    original,
    effective,
    *,
    sheet_name: str,
    candidate_code: str | None,
) -> PilotRow:
    """Adapt M2.1 effective_item output without modifying ORM objects."""
    if original.id != effective.id or original.import_id != effective.import_id:
        raise ValueError("Original and effective item identities differ")
    if original.source_row != effective.source_row:
        raise ValueError("Source row identity changed")
    return PilotRow(
        work_item_id=original.id,
        import_id=original.import_id,
        sheet_name=sheet_name,
        source_row=original.source_row,
        original_description=original.raw_description,
        description=effective.raw_description,
        quantity=str(effective.quantity) if effective.quantity is not None else None,
        unit=effective.normalized_unit,
        candidate_code=candidate_code,
        revision_id=effective.revision_id,
        input_review_required=effective.review_required,
    )


def _validate_rows(rows: tuple[PilotRow, ...]) -> None:
    if not 1 <= len(rows) <= MAX_PILOT_ROWS:
        raise ValueError("Pilot requires 1 to 20 rows")
    seen = set()
    source_cells = set()
    for row in rows:
        if not all((row.work_item_id, row.import_id, row.sheet_name)):
            raise ValueError("Missing row source identity")
        if isinstance(row.source_row, bool) or row.source_row < 1:
            raise ValueError("Invalid Excel source row")
        identity = (row.import_id, row.work_item_id)
        if identity in seen:
            raise ValueError("Duplicate work item in pilot")
        seen.add(identity)
        cell = (row.import_id, row.sheet_name, row.source_row)
        if cell in source_cells:
            raise ValueError("Duplicate Excel source row in pilot")
        source_cells.add(cell)
        if not row.description.strip() or len(row.description) > 10000:
            raise ValueError("Invalid effective description")
        if row.description != row.original_description and not row.revision_id:
            raise ValueError("Changed description requires revision identity")


def _quantity_verified(value: str | None) -> bool:
    try:
        number = Decimal(value) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return False
    return number is not None and number.is_finite() and number >= 0


def review_rows(
    rows: tuple[PilotRow, ...],
    *,
    pdf_path: str | Path | None,
) -> dict:
    """Compare all pilot rows with one verified source loaded at most once.

    This internal service trusts its caller's tenant-authorized row selection.
    It is not a public API and does not grant access to imports or projects.
    """
    _validate_rows(rows)
    supported = any(get_position_support(row.candidate_code) for row in rows)
    analysis = None
    source_status = "not_configured"
    if supported and pdf_path:
        try:
            analysis = read_analysis(pdf_path)
            if (
                analysis["position_code"] != "15.275.1111"
                or analysis["unit"] != "m²"
                or analysis["read_only"] is not True
                or analysis["approval_allowed"] is not False
            ):
                raise ValueError("Unexpected source result")
            source_status = "verified"
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            analysis = None
            source_status = "unverified"
    results = []
    for row in rows:
        result = {
            "identity": {
                "work_item_id": row.work_item_id,
                "import_id": row.import_id,
                "sheet_name": row.sheet_name,
                "source_row": row.source_row,
                "revision_id": row.revision_id,
            },
            "original_description": row.original_description,
            "effective_description": row.description,
            "quantity": row.quantity,
            "unit": row.unit,
            "candidate_code": row.candidate_code,
            "candidate_basis": "explicit_candidate_not_auto_selected",
            "technical_status": "review_required",
            "price_source_status": "not_available",
            "source_price": None,
            "comparison": None,
            "flags": [],
            "review_required": True,
            "approval_allowed": False,
            "cost_scenario": None,
        }
        support = get_position_support(row.candidate_code)
        if row.candidate_code is None:
            result["flags"].append("CANDIDATE_NOT_SELECTED")
        elif support is None:
            result["technical_status"] = "out_of_scope"
            result["flags"].append("POSITION_NOT_SUPPORTED")
        else:
            result["price_source_status"] = source_status
            unit, issues = normalize_unit(row.unit)
            if issues:
                result["flags"].append("UNIT_UNVERIFIED")
            elif unit != support.unit:
                result["flags"].append("UNIT_MISMATCH")
                result["technical_status"] = "incompatible"
            if analysis is None:
                result["flags"].append("PRICE_SOURCE_NOT_VERIFIED")
            else:
                result["source_price"] = {
                    "value": analysis["totals"]["total"],
                    "unit": analysis["unit"],
                    "currency": analysis["totals"]["currency"],
                    "source": deepcopy(analysis["source"]),
                    "applicability": "not_authorized_for_metraj_costing",
                }
                try:
                    comparison = compare_layers(
                        row.description,
                        analysis["technical_description"]["quote"],
                    )
                    if comparison.get("approval_allowed") is not False:
                        raise ValueError("Comparison cannot authorize approval")
                    mapping = {
                        "blocked": "incompatible",
                        "review": "review_required",
                        "layer_match": "checked_features_match",
                    }
                    status = mapping.get(comparison["status"])
                    if status is None:
                        raise ValueError("Unknown comparison status")
                    result["comparison"] = comparison
                    if result["technical_status"] != "incompatible":
                        result["technical_status"] = status
                except (ValueError, KeyError, TypeError):
                    result["flags"].append("COMPARISON_UNVERIFIED")
            if (
                result["flags"]
                and result["technical_status"] == "checked_features_match"
            ):
                result["technical_status"] = "review_required"
        if row.input_review_required:
            result["flags"].append("INPUT_REQUIRES_REVIEW")
        if not _quantity_verified(row.quantity):
            result["flags"].append("QUANTITY_UNVERIFIED")
        if result["flags"] and result["technical_status"] == "checked_features_match":
            result["technical_status"] = "review_required"
        results.append(result)
    counts = {}
    for result in results:
        state = result["technical_status"]
        counts[state] = counts.get(state, 0) + 1
    return {
        "schema": "arkemx.batch_technical_pilot.v1",
        "read_only": True,
        "approval_allowed": False,
        "coverage": "layers_and_critical_attributes_only",
        "row_count": len(results),
        "technical_counts": counts,
        "rows": results,
    }
