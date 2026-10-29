"""A2.2 - Evidence-backed critical technical attribute checks.

Pilot rules only. No approval or pricing authorization.
"""

import re
from decimal import Decimal

from app.technical_analysis.layers import extract_work_scopes, fold

RULES = {
    "cement_dosage_kg": re.compile(
        r"\b(?P<number>\d+(?:[.,]\d+)?)\s*kg\s+cimento\s+dozlu\b"
    ),
    "environment": re.compile(
        r"\b(?P<environment>ic|dis)\s+"
        r"(?:cephe\w*|mekan\w*|duvar\w*)\b"
    ),
    "material_scope": re.compile(
        r"\bmalzeme\s+"
        r"(?P<scope>dahil\s+degil(?:dir)?|haric(?:tir)?|dahil(?:dir)?)\b"
    ),
}


def _matched_value(field: str, match: re.Match):
    if field == "cement_dosage_kg":
        return Decimal(
            match.group("number").replace(",", ".")
        )

    if field == "environment":
        return match.group("environment")

    scope = match.group("scope")
    if "haric" in scope or "degil" in scope:
        return "excluded"

    return "included"


def _extract(text: str, field: str, pattern: re.Pattern) -> dict:
    normalized = fold(text)

    if len(normalized) != len(text):
        raise ValueError("Normalization changed source offsets")

    observations = []

    for match in pattern.finditer(normalized):
        observations.append({
            "value": _matched_value(field, match),
            "evidence": {
                "quote": text[match.start():match.end()],
                "start": match.start(),
                "end": match.end(),
                "offset_basis": "original_text",
            },
        })

    values = {item["value"] for item in observations}

    return {
        "value": next(iter(values)) if len(values) == 1 else None,
        "ambiguous": len(values) > 1,
        "evidence": [
            item["evidence"] for item in observations
        ],
    }


def _compare_work_scopes(left_text: str, right_text: str, skip_fields):
    left = extract_work_scopes(left_text)
    right = extract_work_scopes(right_text)
    checks, blockers, reviews = [], [], []
    for work_type in sorted(set(left) | set(right)):
        field = f"work_scope_{work_type}"
        if field in skip_fields:
            continue
        a_items = left.get(work_type, [])
        b_items = right.get(work_type, [])
        all_items = a_items + b_items
        # Preserve existing positive-only comparison behavior.
        if not any(item["value"] != "included" for item in all_items):
            continue
        a_values = {item["value"] for item in a_items}
        b_values = {item["value"] for item in b_items}
        a = next(iter(a_values)) if len(a_values) == 1 else None
        b = next(iter(b_values)) if len(b_values) == 1 else None
        if len(a_values) > 1 or len(b_values) > 1 or "unknown" in a_values | b_values:
            status, code = "review", f"{field.upper()}_AMBIGUOUS"
        elif a is None or b is None:
            status, code = "review", f"{field.upper()}_UNVERIFIED"
        elif a != b:
            status, code = "block", f"{field.upper()}_MISMATCH"
        else:
            status, code = "match", None
        if status == "block":
            blockers.append(code)
        elif status == "review":
            reviews.append(code)
        checks.append({
            "field": field,
            "status": status,
            "code": code,
            "metraj_value": a if a != "unknown" else None,
            "catalog_value": b if b != "unknown" else None,
            "metraj_evidence": [item["evidence"] for item in a_items],
            "catalog_evidence": [item["evidence"] for item in b_items],
        })
    return checks, blockers, reviews


def compare_critical_attributes(
    metraj_description: str,
    catalog_description: str,
    *,
    skip_fields: frozenset[str] = frozenset(),
) -> tuple[list[dict], list[str], list[str]]:
    """Compare explicitly recognized critical properties.

    Contradictions block; missing or ambiguous values require review.
    Unrecognized fields do not grant approval.
    """

    checks = []
    blockers = []
    reviews = []

    for field, pattern in RULES.items():
        if field in skip_fields:
            continue
        left = _extract(metraj_description, field, pattern)
        right = _extract(catalog_description, field, pattern)

        a = left["value"]
        b = right["value"]

        if (
            a is None
            and b is None
            and not left["ambiguous"]
            and not right["ambiguous"]
        ):
            continue

        if left["ambiguous"] or right["ambiguous"]:
            status = "review"
            code = f"{field.upper()}_AMBIGUOUS"
        elif a is None or b is None:
            status = "review"
            code = f"{field.upper()}_UNVERIFIED"
        elif a != b:
            status = "block"
            code = f"{field.upper()}_MISMATCH"
        else:
            status = "match"
            code = None

        if status == "block":
            blockers.append(code)
        elif status == "review":
            reviews.append(code)

        checks.append({
            "field": field,
            "status": status,
            "code": code,
            "metraj_value": str(a) if a is not None else None,
            "catalog_value": str(b) if b is not None else None,
            "metraj_evidence": left["evidence"],
            "catalog_evidence": right["evidence"],
        })

    scope_checks, scope_blockers, scope_reviews = _compare_work_scopes(
        metraj_description, catalog_description, skip_fields
    )
    checks.extend(scope_checks)
    blockers.extend(scope_blockers)
    reviews.extend(scope_reviews)

    return checks, blockers, reviews
