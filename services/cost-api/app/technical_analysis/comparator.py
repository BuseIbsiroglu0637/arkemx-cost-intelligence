
"""A2.1 - Evidence-backed comparison of technical layers.

This is a partial technical comparison, not an approval engine.
"""

from decimal import Decimal

from app.technical_analysis.layers import (
    LayerMeasurement,
    extract_layer_measurements,
)

FIELDS = ("work_type", "thickness_mm", "materials")


def _serialize_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _layer_record(text: str, layer: LayerMeasurement) -> dict:
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
    """Compare all extracted layers in their original order.

    Unknown or incomplete extraction requires review.
    A layer match never grants engineering approval.
    """

    left_layers = extract_layer_measurements(metraj_description)
    right_layers = extract_layer_measurements(catalog_description)

    left_records = [
        _layer_record(metraj_description, item)
        for item in left_layers
    ]
    right_records = [
        _layer_record(catalog_description, item)
        for item in right_layers
    ]

    blockers = []
    reviews = []
    checks = []

    if not left_layers or not right_layers:
        reviews.append("LAYERS_NOT_EXTRACTED")

    if len(left_layers) != len(right_layers):
        reviews.append("LAYER_COUNT_UNVERIFIED")

    for index, (left, right) in enumerate(
        zip(left_layers, right_layers),
        start=1,
    ):
        for field in FIELDS:
            a = getattr(left, field)
            b = getattr(right, field)

            if a is None or b is None or a == () or b == ():
                status = "review"
                code = f"LAYER_{index}_{field.upper()}_UNVERIFIED"
                reviews.append(code)

            elif a != b:
                status = "block"
                code = f"LAYER_{index}_{field.upper()}_MISMATCH"
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
                "metraj_evidence": left_records[index - 1]["evidence"],
                "catalog_evidence": right_records[index - 1]["evidence"],
            })

    blockers = sorted(set(blockers))
    reviews = sorted(set(reviews))

    status = (
        "blocked"
        if blockers
        else "review"
        if reviews
        else "layer_match"
    )

    return {
        "schema": "arkemx.layer_comparison.v1",
        "status": status,
        "approval_allowed": False,
        "analysis_scope": "layers_only",
        "blockers": blockers,
        "review_flags": reviews,
        "metraj_layers": left_records,
        "catalog_layers": right_records,
        "checks": checks,
    }
