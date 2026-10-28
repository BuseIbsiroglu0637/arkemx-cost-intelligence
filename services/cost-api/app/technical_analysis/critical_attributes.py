
"""A2.2 - Evidence-backed critical technical attribute checks.

Pilot rules only. No approval or pricing authorization.
"""

import re
from decimal import Decimal

from app.technical_analysis.layers import fold

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


def compare_critical_attributes(
    metraj_description: str,
    catalog_description: str,
) -> tuple[list[dict], list[str], list[str]]:
    """Compare explicitly recognized critical properties.

    Contradictions block; missing or ambiguous values require review.
    Unrecognized fields do not grant approval.
    """

    checks = []
    blockers = []
    reviews = []

    for field, pattern in RULES.items():
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

    return checks, blockers, reviews
