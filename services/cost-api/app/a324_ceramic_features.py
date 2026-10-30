"""A3.24: explicit ceramic-finish differences in user-provided PDF candidates.

This module never infers an unmentioned finish, chooses a price or approves a poz.
It only helps the user select a candidate after consulting project specifications.
"""
from __future__ import annotations

import re

from .excel import normalized

WHITE = re.compile(r"\bbeyaz\b")
COLORED = re.compile(r"\brenkli\b")
MATTE = re.compile(r"\bmat\b")
GLOSSY = re.compile(r"\bparlak\b")
UNGLAZED = re.compile(r"\bsirsiz\b")
GLAZED = re.compile(r"\bsirli\b")
RECTIFIED = re.compile(r"\brektifiyeli\b")


def ceramic_features(description: str) -> dict[str, str | None]:
    value = normalized(description)
    glaze = "sirsiz" if UNGLAZED.search(value) else (
        "sirli" if GLAZED.search(value) else None
    )
    color = "beyaz" if WHITE.search(value) else (
        "renkli" if COLORED.search(value) else None
    )
    surface = "mat" if MATTE.search(value) else (
        "parlak" if GLOSSY.search(value) else None
    )
    rectified = "rektifiyeli" if RECTIFIED.search(value) else None
    return {"glaze": glaze, "color": color, "surface": surface,
            "rectified": rectified}


def ceramic_finish_conflict(metraj: str, position: str) -> bool:
    """Block only *explicit* contrary finish claims, not missing information."""
    given = ceramic_features(metraj)
    offered = ceramic_features(position)
    return any(
        given[key] is not None and offered[key] is not None and given[key] != offered[key]
        for key in ("glaze", "color", "surface")
    )


def _label(features: dict[str, str | None]) -> str | None:
    names = {
        "mat": "Mat", "parlak": "Parlak", "sirsiz": "sırsız",
        "sirli": "sırlı", "beyaz": "beyaz", "renkli": "renkli",
        "rektifiyeli": "rektifiyeli",
    }
    fields = [
        features["color"], features["surface"], features["glaze"],
        features["rectified"] if features["glaze"] == "sirsiz" else None,
    ]
    rendered = [names[field] for field in fields if field]
    return ", ".join(rendered) if rendered else None


def ceramic_question(metraj: str, suggestions: list[dict]) -> dict | None:
    """Return one compact question, only with distinguishable PDF options.

    Every displayed option is an existing, nonblocked candidate code. Unclear
    or duplicate finish labels must not produce a pseudo-confirmed choice.
    """
    if len(suggestions) < 2:
        return None
    given = ceramic_features(metraj)
    options = []
    for candidate in suggestions:
        if candidate.get("technical_status") == "blocked":
            continue
        desc = candidate["description"]
        if ceramic_finish_conflict(metraj, desc):
            continue
        features = ceramic_features(desc)
        label = _label(features)
        if not label:
            return None
        options.append({"code": candidate["code"], "label": label,
                        "source_page": candidate.get("source_page")})
    if len(options) < 2:
        return None
    if len({option["label"] for option in options}) != len(options):
        return None
    # No question when the Excel has already resolved all differences.
    differing_keys = {
        key for key in ("glaze", "color", "surface", "rectified")
        if len({ceramic_features(candidate["description"])[key]
                for candidate in suggestions
                if candidate.get("technical_status") != "blocked"}) > 1
        and given[key] is None
    }
    if not differing_keys:
        return None
    return {
        "key": "ceramic_finish",
        "prompt": "Projede hangi porselen seramik türü belirtiliyor?",
        "hint": "Mimari şartnameye göre seç. Bilmiyorsan seçim yapma; teknik onay verilmez.",
        "options": options,
        "approval_allowed": False,
        "cost_allowed": False,
    }
