
"""A2.4 - Source-backed cement dosage comparison per layer.

Unassigned or conflicting dosage expressions require review.
Never grants engineering approval.
"""

import re
from collections.abc import Sequence
from decimal import Decimal

from app.technical_analysis.layers import LayerMeasurement, fold

DOSAGE = re.compile(
    r"\b(?P<value>\d+(?:[.,]\d+)?)\s*kg\s+cimento\s+dozlu\b"
)


def _collect_dosages(
    text: str,
    layers: Sequence[LayerMeasurement],
) -> tuple[list[list[dict]], bool, bool]:
    normalized = fold(text)

    if len(normalized) != len(text):
        raise ValueError("Source offsets are not preserved")

    by_layer: list[list[dict]] = [[] for _ in layers]
    unassigned = False
    found = False

    for match in DOSAGE.finditer(normalized):
        found = True

        owners = [
            index
            for index, layer in enumerate(layers)
            if (
                layer.start <= match.start()
                and match.end() <= layer.end
            )
        ]

        if len(owners) != 1:
            unassigned = True
            continue

        evidence = {
            "quote": text[match.start():match.end()],
            "start": match.start(),
            "end": match.end(),
            "offset_basis": "original_text",
        }

        by_layer[owners[0]].append({
            "value": Decimal(
                match.group("value").replace(",", ".")
            ),
            "evidence": evidence,
        })

    return by_layer, unassigned, found


def compare_layer_dosages(
    metraj_description: str,
    catalog_description: str,
    metraj_layers: Sequence[LayerMeasurement],
    catalog_layers: Sequence[LayerMeasurement],
) -> tuple[list[dict], list[str], list[str]]:
    """Compare dosage only where source-to-layer ownership is clear."""

    left, left_unassigned, left_found = _collect_dosages(
        metraj_description,
        metraj_layers,
    )
    right, right_unassigned, right_found = _collect_dosages(
        catalog_description,
        catalog_layers,
    )

    if not left_found and not right_found:
        return [], [], []

    checks: list[dict] = []
    blockers: list[str] = []
    reviews: list[str] = []

    count = max(len(left), len(right))

    for index in range(count):
        left_items = left[index] if index < len(left) else []
        right_items = right[index] if index < len(right) else []

        prefix = f"LAYER_{index + 1}_" if count > 1 else ""
        field = "CEMENT_DOSAGE_KG"

        if len(left_items) > 1 or len(right_items) > 1:
            status = "review"
            code = f"{prefix}{field}_AMBIGUOUS"
            reviews.append(code)

        elif len(left_items) != 1 or len(right_items) != 1:
            status = "review"
            code = f"{prefix}{field}_UNVERIFIED"
            reviews.append(code)

        elif left_items[0]["value"] != right_items[0]["value"]:
            status = "block"
            code = f"{prefix}{field}_MISMATCH"
            blockers.append(code)

        else:
            status = "match"
            code = None

        checks.append({
            "layer": index + 1,
            "field": "cement_dosage_kg",
            "status": status,
            "code": code,
            "metraj_value": (
                str(left_items[0]["value"])
                if len(left_items) == 1 else None
            ),
            "catalog_value": (
                str(right_items[0]["value"])
                if len(right_items) == 1 else None
            ),
            "metraj_evidence": [
                item["evidence"] for item in left_items
            ],
            "catalog_evidence": [
                item["evidence"] for item in right_items
            ],
        })

    if left_unassigned or right_unassigned:
        reviews.append("CEMENT_DOSAGE_KG_UNASSIGNED")

    return checks, blockers, reviews
