
"""A2.2 - Evidence-backed technical layer comparison.

Compares layer structure, thickness, materials and critical
technical attributes.

This is a partial technical comparison, not an approval engine.
"""

from decimal import Decimal

from app.technical_analysis.critical_attributes import (
    compare_critical_attributes,
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
    """Serialize a layer while verifying its source evidence."""

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

    Layer checks:
        - Work type
        - Thickness
        - Materials
        - Layer count and order

    Additional checks:
        - Cement mortar dosage
        - Internal/external environment
        - Material inclusion/exclusion

    Unknown or incomplete extraction requires review.

    A layer match never grants engineering approval.
    """

    # --------------------------------------------------
    # 1. Extract technical layers
    # --------------------------------------------------

    left_layers = extract_layer_measurements(
        metraj_description
    )

    right_layers = extract_layer_measurements(
        catalog_description
    )

    # --------------------------------------------------
    # 2. Validate source evidence
    # --------------------------------------------------

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

    # --------------------------------------------------
    # 3. Check layer availability and count
    # --------------------------------------------------

    if not left_layers or not right_layers:
        reviews.append("LAYERS_NOT_EXTRACTED")

    if len(left_layers) != len(right_layers):
        reviews.append("LAYER_COUNT_UNVERIFIED")

    # --------------------------------------------------
    # 4. Compare layers in their original order
    # --------------------------------------------------

    for index, (left, right) in enumerate(
        zip(left_layers, right_layers),
        start=1,
    ):
        for field in FIELDS:
            a = getattr(left, field)
            b = getattr(right, field)

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
                ),
                "catalog_evidence": (
                    right_records[index - 1]["evidence"]
                ),
            })

    # --------------------------------------------------
    # 5. Compare critical technical attributes (A2.2)
    # --------------------------------------------------

    technical_checks, extra_blockers, extra_reviews = (
        compare_critical_attributes(
            metraj_description,
            catalog_description,
        )
    )

    blockers.extend(extra_blockers)
    reviews.extend(extra_reviews)

    # --------------------------------------------------
    # 6. Normalize decision reasons
    # --------------------------------------------------

    blockers = sorted(set(blockers))
    reviews = sorted(set(reviews))

    # --------------------------------------------------
    # 7. Determine partial comparison status
    # --------------------------------------------------

    status = (
        "blocked"
        if blockers
        else "review"
        if reviews
        else "layer_match"
    )

    # --------------------------------------------------
    # 8. Return source-backed comparison
    # --------------------------------------------------

    return {
        "schema": "arkemx.layer_comparison.v1",
        "status": status,

        # A2 cannot authorize engineering approval.
        "approval_allowed": False,

        "analysis_scope": "layers_and_critical_attributes",

        "blockers": blockers,
        "review_flags": reviews,

        "metraj_layers": left_records,
        "catalog_layers": right_records,

        "checks": checks,
        "technical_checks": technical_checks,
    }
