"""A3.20: evidence-first assistance for ambiguous PDF poz proposals.

Keeps automatic retrieval read-only. Missing engineering facts are review issues,
not guessed values. Related plaster rows are never automatically merged/priced.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .excel import normalized
from .a324_ceramic_features import ceramic_finish_conflict
from .a335_plaster_matching import plaster_checks, plaster_stages
from .matching import dimensions, evaluate, family, find_candidates, similarity

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


def _known_location(value: str) -> tuple[str | None, str | None]:
    text = _text(value)
    zone = ("dis" if "dis cephe" in text else
            "ic" if "ic cephe" in text else None)
    surface = ("tavan" if "tavan" in text else
               "zemin" if "zemin" in text else
               "duvar" if "duvar" in text else None)
    return zone, surface


def _locations_conflict(left: str, right: str) -> bool:
    return any(a is not None and b is not None and a != b for a, b in
               zip(_known_location(left), _known_location(right)))


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
        for item in group:
            valid_opposite = [
                other for other in opposite
                if not _locations_conflict(item.raw_description, other.raw_description)
            ]
            if not valid_opposite:
                continue
            pairs[str(item.id)] = sorted({int(other.source_row) for other in valid_opposite})
            for other in valid_opposite:
                pairs.setdefault(str(other.id), []).append(int(item.source_row))
    return {item_id: sorted(set(rows)) for item_id, rows in pairs.items()}


def find_pdf_candidates(item, positions) -> list[dict]:
    """Reuse strict M2 retrieval, with a bounded class/family fallback.

    Neither generic similarity nor a repeated quantity authorizes a priced match.
    """
    desc = item.raw_description
    initial = find_candidates(item, positions)
    cls = _concrete(desc)
    is_paint = _paint(desc)
    is_ceramic = family(desc) == "seramik"
    if PLASTER.search(_text(desc)) and plaster_stages(desc):
        # A3.35: lexical top-3 can be crowded by the *other* plaster layer.
        # Search only PDF-grounded plaster positions, rank matching stages
        # before unspecified descriptions, and let strict checks block clashes.
        from .matching import dimensions as measured_dimensions
        source_stages = plaster_stages(desc)
        _, source_thickness = measured_dimensions(desc)
        plaster_results = []
        for position in positions:
            # Some official descriptions say "sıvanması" rather than "sıva";
            # the old exact family-token match would discard them.
            position_family = family(position.description)
            if (not PLASTER.search(_text(position.description)) or
                    position_family not in (None, "siva")):
                continue
            score = similarity(desc, position.description)
            stages = plaster_stages(position.description)
            _, candidate_thickness = measured_dimensions(position.description)
            if score < 0.08 and stages != source_stages:
                continue
            result = evaluate(item, position)
            if result is None:
                if score < 0.08:
                    continue
                result = {
                    "position_id": position.id, "similarity": score,
                    "reasons": ["Poz PDF'sindeki sıva katmanı ayrıca doğrulanmalı"],
                    "warnings": ["LOW_LEXICAL_SIMILARITY"], "approvable": False,
                }
            incompatible, _ = plaster_checks(desc, position.description)
            thickness_conflict = bool(
                source_thickness and candidate_thickness
                and source_thickness != candidate_thickness
            )
            unit_conflict = item.normalized_unit != position.unit
            plaster_results.append((
                result, stages, incompatible, thickness_conflict, unit_conflict,
                bool(source_thickness and candidate_thickness
                     and source_thickness == candidate_thickness),
            ))
        plaster_results.sort(key=lambda entry: (
            int(bool(entry[2]) or entry[3] or entry[4]),
            int(entry[1] != source_stages),
            -int(entry[5]),
            -entry[0]["similarity"], entry[0]["position_id"],
        ))
        # Return up to three real PDF candidates; contradictory candidates
        # remain blocked/removed by _pdf_candidate_check in the API.
        return [entry[0] for entry in plaster_results[:3]]
    if not cls and not is_paint and not is_ceramic:
        return initial
    source_dims, _ = dimensions(desc)
    lookup = {position.id: position for position in positions}
    keyed = {
        entry["position_id"]: entry for entry in initial
        if not (is_ceramic and ceramic_finish_conflict(
            desc, lookup[entry["position_id"]].description,
        ))
    }
    for position in positions:
        if position.id in keyed:
            continue
        position_desc = position.description
        if is_ceramic and ceramic_finish_conflict(desc, position_desc):
            continue
        score = similarity(desc, position_desc)
        if cls:
            if family(position_desc) != "beton" or _concrete(position_desc) != cls:
                continue
            if score < 0.08:
                continue
        elif is_ceramic:
            if family(position_desc) != "seramik" or score < 0.10:
                continue
            position_dims, _ = dimensions(position_desc)
            # Explicit opposing dimensions must never be presented as a likely
            # match, even when the finish material and words are similar.
            if source_dims and position_dims and source_dims != position_dims:
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
        # Explicit matching ceramic dimensions win over generic "kaplama"
        # descriptions. Still only candidates; not a technical approval.
        -int(bool(is_ceramic and source_dims and
                  dimensions(lookup[entry["position_id"]].description)[0] == source_dims)),
        -int(bool(cls) and _concrete(
            lookup[entry["position_id"]].description) == cls),
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
    plaster_blockers, plaster_reviews = plaster_checks(description, position_description)
    blockers.update(plaster_blockers)
    reviews.update(plaster_reviews)
    if plaster_partner_rows:
        reviews.add("POSSIBLE_COMBINED_PLASTER_SCOPE")
    return {
        **check, "blockers": sorted(blockers), "review_flags": sorted(reviews),
        "status": "blocked" if blockers else "review" if reviews else check["status"],
    }


def issue_summary(description: str, suggestions: list[dict],
                  plaster_partner_rows: list[int] | None = None) -> str | None:
    if plaster_partner_rows:
        if not suggestions:
            return (
                "Kaba ve ince sıva için ayrı, uyumlu poz bulunamadı; birleşik "
                "poz iki ayrı satıra uygulanamaz. PDF tarifini kontrol et."
            )
        return (
            "Kaba ve ince sıva ayrı katmanlardır; birleşik poz varsa "
            "aynı yüzeyin çift fiyatlanmaması için kapsam kontrol edilmeli."
        )
    if not suggestions:
        return "PDF'de doğrulanabilir aday bulunamadı. Teknik tarif kontrol edilmeli."
    checks = suggestions[0]
    issues = set(checks["review_flags"]) | set(checks["blockers"])
    if "GAZBETON_STRENGTH_N_MM2_UNVERIFIED" in issues or (
        "GAZBETON_DENSITY_KG_M3_UNVERIFIED" in issues
    ):
        return "Gazbeton dayanımı veya yoğunluğu metrajda eksik."
    if "PLASTER_LAYER_UNVERIFIED" in issues:
        return "Poz tarifinde kaba/ince sıva katmanı açık değil. Teknik şartname ve analiz kapsamı kontrol edilmeli."
    if "PLASTER_BINDER_UNVERIFIED" in issues:
        return "Sıva harcı türü (çimento/alçı/kireç) metraj ve poz arasında doğrulanmalı."
    if "PLASTER_CEMENT_DOSAGE_UNVERIFIED" in issues:
        return "Sıva çimento dozajı poz tarifinde doğrulanmalı."
    if "CONCRETE_CLASS_MISMATCH" in issues or "CONCRETE_CLASS_UNVERIFIED" in issues:
        return "Beton sınıfının poz tarifinde doğrulanması gerekiyor."
    if "PAINT_BASE_UNVERIFIED" in issues:
        return "Su bazlı boya türü poz tarifinde doğrulanmalı."
    if checks["technical_status"] == "blocked":
        return "Teknik çelişki var; aday onaylanamaz."
    if checks["technical_status"] == "review":
        return "Pozun teknik özellikleri kontrol edilmeli."
    return None
