"""A2.4 - Evidence-backed technical layer comparison.

Compares:
- Layer structure and order
- Thickness and materials
- Cement dosage per layer
- Internal/external environment
- Material inclusion/exclusion

This is a partial comparison, not an engineering approval engine.
"""

from decimal import Decimal
from itertools import zip_longest

from app.technical_analysis.critical_attributes import (
    compare_critical_attributes,
)
from app.technical_analysis.layer_dosage import (
    compare_layer_dosages,
)
from app.technical_analysis.layers import (
    LayerMeasurement,
    extract_layer_measurements,
)

FIELDS = ("work_type", "thickness_mm", "materials")


def _serialize_value(value):
    """Convert internal values into JSON-compatible values."""

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, tuple):
        return list(value)

    return value


def _layer_record(
    text: str,
    layer: LayerMeasurement,
) -> dict:
    """Serialize a layer and verify its source evidence."""

    if not (
        0 <= layer.start < layer.end <= len(text)
        and text[layer.start:layer.end] == layer.quote
    ):
        raise ValueError("Invalid source evidence span")

    return {
        "order": layer.order,
        "work_type": layer.work_type,
        "thickness_mm": str(layer.thickness_mm),
        "materials": list(layer.materials),
        "evidence": {
            "quote": layer.quote,
            "start": layer.start,
            "end": layer.end,
            "offset_basis": "original_text",
        },
    }


def compare_layers(
    metraj_description: str,
    catalog_description: str,
) -> dict:
    """Compare technical layers and critical attributes.

    An unresolved property requires review.

    A technical match does not grant engineering approval.
    """

    # 1. Extract source-backed layers.

    left_layers = extract_layer_measurements(
        metraj_description
    )

    right_layers = extract_layer_measurements(
        catalog_description
    )

    # 2. Validate and serialize evidence.

    left_records = [
        _layer_record(metraj_description, item)
        for item in left_layers
    ]

    right_records = [
        _layer_record(catalog_description, item)
        for item in right_layers
    ]

    blockers: list[str] = []
    reviews: list[str] = []
    checks: list[dict] = []

    # 3. Validate layer availability and count.

    if not left_layers or not right_layers:
        reviews.append("LAYERS_NOT_EXTRACTED")

    if len(left_layers) != len(right_layers):
        reviews.append("LAYER_COUNT_UNVERIFIED")

    # 4. Compare extracted layers in source order, including unmatched ones.
    # A missing extraction has no inferred value or fabricated evidence.

    for index, (left, right) in enumerate(
        zip_longest(left_layers, right_layers),
        start=1,
    ):
        for field in FIELDS:
            a = getattr(left, field) if left is not None else None
            b = getattr(right, field) if right is not None else None

            if (
                a is None
                or b is None
                or a == ()
                or b == ()
            ):
                status = "review"
                code = (
                    f"LAYER_{index}_"
                    f"{field.upper()}_UNVERIFIED"
                )
                reviews.append(code)

            elif a != b:
                status = "block"
                code = (
                    f"LAYER_{index}_"
                    f"{field.upper()}_MISMATCH"
                )
                blockers.append(code)

            else:
                status = "match"
                code = None

            checks.append({
                "layer": index,
                "field": field,
                "status": status,
                "code": code,
                "metraj_value": _serialize_value(a),
                "catalog_value": _serialize_value(b),
                "metraj_evidence": (
                    left_records[index - 1]["evidence"]
                    if left is not None else None
                ),
                "catalog_evidence": (
                    right_records[index - 1]["evidence"]
                    if right is not None else None
                ),
            })

    # 5. A2.4 - Compare cement dosage within each layer.
    #
    # Do not compare all dosage numbers as a global set.
    # Each dosage must belong to a specific source layer.

    dosage_checks, dosage_blockers, dosage_reviews = (
        compare_layer_dosages(
            metraj_description,
            catalog_description,
            left_layers,
            right_layers,
        )
    )

    blockers.extend(dosage_blockers)
    reviews.extend(dosage_reviews)

    # 6. A2.2 - Compare other critical attributes.
    #
    # Cement dosage is excluded here because A2.4 handles it
    # at the layer level. This avoids false ambiguity flags.

    technical_checks, extra_blockers, extra_reviews = (
        compare_critical_attributes(
            metraj_description,
            catalog_description,
            skip_fields=frozenset({
                "cement_dosage_kg",
            }),
        )
    )

    blockers.extend(extra_blockers)
    reviews.extend(extra_reviews)

    # Include layer-specific dosage evidence in the output.

    technical_checks.extend(dosage_checks)

    # 7. Normalize decision reasons.

    blockers = sorted(set(blockers))
    reviews = sorted(set(reviews))

    # 8. Determine the partial technical status.

    if blockers:
        status = "blocked"
    elif reviews:
        status = "review"
    else:
        status = "layer_match"

    # 9. Return a source-backed comparison.

    return {
        "schema": "arkemx.layer_comparison.v1",
        "status": status,

        # Never authorize engineering approval here.
        "approval_allowed": False,

        "analysis_scope": (
            "layers_and_critical_attributes"
        ),

        "blockers": blockers,
        "review_flags": reviews,

        "metraj_layers": left_records,
        "catalog_layers": right_records,

        "checks": checks,
        "technical_checks": technical_checks,
    }
