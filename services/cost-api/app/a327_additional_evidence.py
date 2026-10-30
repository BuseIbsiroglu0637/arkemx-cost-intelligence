"""A3.27.3: conservative project-PDF fact extraction for unapproved works.

Evidence is tied to a printed PDF page. This module never certifies work
scope, engineering suitability, dosage, or an official price.
"""
from __future__ import annotations

import re

from .excel import normalized
from .matching import family
from .a335_plaster_matching import plaster_stages, plaster_dosages

LAYER_BEFORE = re.compile(
    # Allow a short material qualifier, e.g. "20 mm çimento esaslı kaba sıva".
    # Do not cross another layer name, an earlier "sıva", or sentence marks.
    r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(mm|cm)\s+"
    r"(?:(?!(?:kaba|ince|siva)\b)\w+\s+){0,4}(kaba|ince)\s+siva\b"
)
LAYER_AFTER = re.compile(
    r"\b(kaba|ince)\s+siva\s+(\d+(?:[.,]\d+)?)\s*(mm|cm)\b"
)
CONCRETE = re.compile(r"\bc\s*(\d{2})\s*/\s*(\d{2})\b")
COATS = re.compile(r"\b(\d{1,2})\s*kat\b|\bkat\s+sayisi\s*[:=]?\s*(\d{1,2})\b")


def _layer_values(value: str) -> list[tuple[str, int | float]]:
    """Keep only explicit stage/thickness pairings (no guessed layers)."""
    plain = normalized(value)
    found: set[tuple[str, float]] = set()
    for match in LAYER_BEFORE.finditer(plain):
        number = float(match[1].replace(",", "."))
        found.add((match[3], number * (10 if match[2] == "cm" else 1)))
    for match in LAYER_AFTER.finditer(plain):
        number = float(match[2].replace(",", "."))
        found.add((match[1], number * (10 if match[3] == "cm" else 1)))
    return sorted(found)


def _paint_bases(plain: str) -> set[str]:
    result = set()
    if re.search(r"\bsu\s+bazli\b", plain):
        result.add("su bazli")
    if re.search(r"\b(?:solvent|sentetik)\s+bazli\b", plain):
        result.add("solvent bazli")
    return result


def additional_matches(description: str, blocks: list[tuple[int, str]]) -> list[dict]:
    """Return factual snippets for *this* row; never transfer facts across stages.

    If a PDF paragraph contains both plaster layers, only the requested stage
    is emitted. Multiple values remain separate to trigger conflict detection.
    """
    kind = family(description)
    plain_description = normalized(description)
    result: list[dict] = []

    if kind == "siva":
        # Shared source extraction with A3.38. Both the old /a326/evidence
        # and the new comparison must agree on exactly the same PDF blocks.
        stages = plaster_stages(description)
        if len(stages) != 1:
            return []
        desired = next(iter(stages))
        for page, text in blocks:
            if "siva" not in normalized(text):
                continue
            for stage, thickness in _layer_values(text):
                if stage == desired:
                    result.append({
                        "page": page, "quote": text[:320],
                        "facts": {"layer_type": stage, "layer_thickness_mm": thickness},
                    })
            # If both stages are mentioned in the same text block, a single
            # dosage cannot safely be assigned to either stage. No guessing.
            if plaster_stages(text) != stages:
                continue
            for amount in sorted(plaster_dosages(text)):
                value = int(amount) if amount == amount.to_integral_value() else float(amount)
                result.append({
                    "page": page, "quote": text[:320],
                    "facts": {"layer_type": desired, "cement_dosage_kg": value},
                })
    elif kind == "beton":
        if not re.search(r"\bbeton\w*\b", plain_description):
            return []
        for page, text in blocks:
            plain = normalized(text)
            if not re.search(r"\bbeton\w*\b", plain):
                continue
            classes = {f"C{a}/{b}" for a, b in CONCRETE.findall(plain)}
            for class_name in sorted(classes):
                result.append({"page": page, "quote": text[:320],
                               "facts": {"concrete_class": class_name}})
    elif kind == "boya":
        if not re.search(r"\bboya\w*\b", plain_description):
            return []
        for page, text in blocks:
            plain = normalized(text)
            if not re.search(r"\bboya\w*\b", plain):
                continue
            bases = _paint_bases(plain)
            coat_counts = {int(a or b) for a, b in COATS.findall(plain)}
            # Do not silently treat many competing values as one.
            for base in sorted(bases or {None}):
                for coats in sorted(coat_counts or {None}, key=lambda x: (x is None, x or 0)):
                    if base is None and coats is None:
                        continue
                    result.append({"page": page, "quote": text[:320],
                                   "facts": {"paint_base": base, "coat_count": coats}})
    return result


def conflicts_with_metraj(description: str, matches: list[dict]) -> bool:
    """Detect explicit disagreement with Excel, never invent missing values."""
    kind = family(description)
    original = normalized(description)
    if kind == "siva":
        stages = set(re.findall(r"\b(kaba|ince)\s+siva\b", original))
        measured = {value for stage, value in _layer_values(original) if stage in stages}
        observed = {row["facts"]["layer_thickness_mm"] for row in matches
                    if row["facts"].get("layer_thickness_mm") is not None}
        return bool(measured and observed and measured != observed)
    if kind == "beton":
        expected = {f"C{a}/{b}" for a, b in CONCRETE.findall(original)}
        actual = {row["facts"]["concrete_class"] for row in matches
                  if row["facts"].get("concrete_class")}
        return bool(expected and actual and expected != actual)
    if kind == "boya":
        expected_bases = _paint_bases(original)
        actual_bases = {row["facts"]["paint_base"] for row in matches
                        if row["facts"].get("paint_base")}
        expected_coats = {int(a or b) for a, b in COATS.findall(original)}
        actual_coats = {row["facts"]["coat_count"] for row in matches
                        if row["facts"].get("coat_count") is not None}
        return bool(
            (expected_bases and actual_bases and expected_bases != actual_bases)
            or (expected_coats and actual_coats and expected_coats != actual_coats)
        )
    return False
