"""A2.5 - Source-backed cement dosage comparison per layer.

Supports legacy 'cimento dozlu' and selected real-analysis expressions.
New addition expressions require an explicit one-cubic-metre sand basis.
Missing, conflicting or unassigned information requires review.
Never grants engineering approval.
"""

import re
from collections.abc import Sequence
from decimal import Decimal

from app.technical_analysis.layers import LayerMeasurement, fold

DOSAGE = re.compile(
    r"\b(?P<value>\d+(?:[.,]\d+)?)\s*kg\s+cimento\s+"
    r"(?P<expression>dozlu|katilmasi|ilavesiyle)\b"
)

CEMENT_AMOUNT = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*kg\s+cimento\b"
)

SAND_BASIS = re.compile(
    r"\b(?P<value>\d+(?:[.,]\d+)?)\s*m(?:³|3|\^3)\s+"
    r"(?:disli\s+|mil\s+)?kum(?:a|una)\b"
)


def _has_unit_sand_basis(text: str) -> bool:
    """Require exactly one explicit reference to one cubic metre of sand."""
    matches = list(SAND_BASIS.finditer(text))

    return (
        len(matches) == 1
        and Decimal(
            matches[0].group("value").replace(",", ".")
        ) == Decimal("1")
    )


def _collect_dosages(
    text: str,
    layers: Sequence[LayerMeasurement],
) -> tuple[list[list[dict]], bool, bool]:
    normalized = fold(text)

    if len(normalized) != len(text):
        raise ValueError("Source offsets are not preserved")

    matches = list(DOSAGE.finditer(normalized))
    amounts = list(CEMENT_AMOUNT.finditer(normalized))

    recognized_starts = {
        match.start() for match in matches
    }

    # Unrecognized cement-amount expressions must not disappear silently.
    unassigned = any(
        amount.start() not in recognized_starts
        for amount in amounts
    )

    found = bool(amounts)
    by_layer: list[list[dict]] = [[] for _ in layers]

    for match in matches:
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

        owner = owners[0]
        layer = layers[owner]

        # Preserve legacy "cimento dozlu" support.
        # New addition expressions need a clear local sand-volume basis.
        if match.group("expression") != "dozlu":
            prefix = normalized[layer.start:match.start()]

            if not _has_unit_sand_basis(prefix):
                unassigned = True
                continue

        by_layer[owner].append({
            "value": Decimal(
                match.group("value").replace(",", ".")
            ),
            "evidence": {
                "quote": text[match.start():match.end()],
                "start": match.start(),
                "end": match.end(),
                "offset_basis": "original_text",
            },
        })

    return by_layer, unassigned, found


def compare_layer_dosages(
    metraj_description: str,
    catalog_description: str,
    metraj_layers: Sequence[LayerMeasurement],
    catalog_layers: Sequence[LayerMeasurement],
) -> tuple[list[dict], list[str], list[str]]:
    """Compare recognized dosage only where layer ownership is clear."""

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