"""A3.20: evidence-first assistance for ambiguous PDF poz proposals.

Keeps automatic retrieval read-only. Missing engineering facts are review issues,
not guessed values. Related plaster rows are never automatically merged/priced.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .excel import normalized
from .matching import evaluate, family, find_candidates, similarity

CONCRETE_CLASS = re.compile(r"(?<![a-z0-9])c\s*(\d{2})\s*/\s*(\d{2})(?!\d)")
PAINT_WORD = re.compile(r"\bboya\w*|\bboyan\w*")
PLASTER = re.compile(r"\bsiva\w*")


def _text(value: str) -> str:
    return normalized(value)


def _concrete(value: str) -> str | None:
    match = CONCRETE_CLASS.search(_text(value))
    return f"C{match[1]}/{match[2]}" if match else None


def _paint(value: str) -> bool:
    return bool(PAINT_WORD.search(_text(value)))


def _water_based(value: str) -> bool:
    text = _text(value)
    return "su bazli" in text or "su esasli" in text


def _is_plaster(value: str, layer: str) -> bool:
    text = _text(value)
    return bool(PLASTER.search(text)) and bool(re.search(rf"\b{layer}\b", text))


def potential_plaster_pairs(items) -> dict[str, list[int]]:
    """Equal quantities identify a *review hint*, never verified common area.

    Only an explicit coarse/fine pairing is surfaced. No row is removed or merged.
    """
    buckets: dict[tuple[str, Decimal, str], list] = {}
    for item in items:
        layer = "kaba" if _is_plaster(item.raw_description, "kaba") else (
            "ince" if _is_plaster(item.raw_description, "ince") else None
        )
        if not layer or item.quantity is None or not item.normalized_unit:
            continue
        key = (layer, Decimal(str(item.quantity)), item.normalized_unit)
        buckets.setdefault(key, []).append(item)
    pairs: dict[str, list[int]] = {}
    for (layer, quantity, unit), group in buckets.items():
        if layer != "kaba":
            continue
        opposite = buckets.get(("ince", quantity, unit), [])
        if not opposite:
            continue
        for item in group:
            pairs[str(item.id)] = sorted({int(other.source_row) for other in opposite})
        for item in opposite:
            pairs[str(item.id)] = sorted({int(other.source_row) for other in group})
    return pairs


def find_pdf_candidates(item, positions) -> list[dict]:
    """Reuse strict M2 retrieval, with a bounded class/family fallback.

    Neither generic similarity nor a repeated quantity authorizes a priced match.
    """
    initial = find_candidates(item, positions)
    desc = item.raw_description
    cls = _concrete(desc)
    is_paint = _paint(desc)
    if not cls and not is_paint:
        return initial
    keyed = {entry["position_id"]: entry for entry in initial}
    for position in positions:
        if position.id in keyed:
            continue
        position_desc = position.description
        score = similarity(desc, position_desc)
        if cls:
            if family(position_desc) != "beton" or _concrete(position_desc) != cls:
                continue
            if score < 0.08:
                continue
        elif is_paint:
            if not _paint(position_desc) or score < 0.14:
                continue
            # Skip obviously opposing interior/exterior environments.
            left = _text(desc)
            right = _text(position_desc)
            if ("ic cephe" in left and "dis cephe" in right) or (
                "dis cephe" in left and "ic cephe" in right
            ):
                continue
        result = evaluate(item, position)
        if result is None:
            result = {
                "position_id": position.id, "similarity": score, "reasons": [],
                "warnings": ["LOW_LEXICAL_SIMILARITY"], "approvable": False,
            }
        keyed[position.id] = result
    ordered = list(keyed.values())
    ordered.sort(key=lambda entry: (
        -int(bool(cls) and _concrete(next(
            p.description for p in positions if p.id == entry["position_id"]
        )) == cls),
        -entry["similarity"], entry["position_id"],
    ))
    return ordered[:3]


def enrich_technical(description: str, position_description: str, check: dict,
                     *, plaster_partner_rows: list[int] | None = None) -> dict:
    """Additional construction gates; status is never upgraded."""
    blockers = set(check["blockers"])
    reviews = set(check["review_flags"])
    source_class = _concrete(description)
    if source_class:
        candidate_class = _concrete(position_description)
        if candidate_class is None:
            reviews.add("CONCRETE_CLASS_UNVERIFIED")
        elif source_class != candidate_class:
            blockers.add("CONCRETE_CLASS_MISMATCH")
    if _paint(description) and _water_based(description):
        if not _water_based(position_description):
            reviews.add("PAINT_BASE_UNVERIFIED")
    if plaster_partner_rows:
        reviews.add("POSSIBLE_COMBINED_PLASTER_SCOPE")
    return {
        **check, "blockers": sorted(blockers), "review_flags": sorted(reviews),
        "status": "blocked" if blockers else "review" if reviews else check["status"],
    }


def issue_summary(description: str, suggestions: list[dict],
                  plaster_partner_rows: list[int] | None = None) -> str | None:
    if plaster_partner_rows:
        return "Kaba ve ince sıva aynı yüzeyde olabilir; birleşik poz kapsamı kontrol edilmeli."
    if not suggestions:
        return "PDF'de doğrulanabilir aday bulunamadı. Teknik tarif kontrol edilmeli."
    checks = suggestions[0]
    issues = set(checks["review_flags"]) | set(checks["blockers"])
    if "GAZBETON_STRENGTH_N_MM2_UNVERIFIED" in issues or (
        "GAZBETON_DENSITY_KG_M3_UNVERIFIED" in issues
    ):
        return "Gazbeton dayanımı veya yoğunluğu metrajda eksik."
    if "CONCRETE_CLASS_MISMATCH" in issues or "CONCRETE_CLASS_UNVERIFIED" in issues:
        return "Beton sınıfının poz tarifinde doğrulanması gerekiyor."
    if "PAINT_BASE_UNVERIFIED" in issues:
        return "Su bazlı boya türü poz tarifinde doğrulanmalı."
    if checks["technical_status"] == "blocked":
        return "Teknik çelişki var; aday onaylanamaz."
    if checks["technical_status"] == "review":
        return "Pozun teknik özellikleri kontrol edilmeli."
    return None
