"""A3.50.1 — source-grounded construction work taxonomy.

Classifies *work objects*, not merely shared materials (seramik/PVC) or
unverified brand names. Deterministic classification is an aid to retrieval,
NEVER engineering approval, a matched poz, or a price calculation.

Do not infer object type from a position's code, publisher, price, or nearby
different position. All positive signals must exist in the given description.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .excel import normalized

TAXONOMY_VERSION = "a3501-work-object-v1"

LABELS = {
    "gazbeton_wall": "Gazbeton duvar",
    "brick_wall": "Tuğla duvar",
    "ceramic_surface": "Seramik / karo kaplama",
    "pvc_floor": "PVC yer kaplaması",
    "pvc_profile": "PVC profil",
    "pvc_pipework": "PVC boru / tesisat",
    "pvc_joinery": "PVC doğrama",
    "plumbing_tap": "Musluk / batarya",
    "plumbing_fixture": "Sıhhi tesisat armatürü",
    "plaster_cement": "Çimento esaslı sıva",
    "plaster_gypsum": "Alçı sıva",
    "plaster_generic": "Sıva (türü belirsiz)",
    "cement_surface_coating": "Çimento esaslı yüzey kaplaması",
    "waterproofing": "Su yalıtımı",
    "thermal_insulation": "Isı yalıtımı",
    "paint": "Boya",
    "window_door": "Kapı / pencere / doğrama",
    "concrete_work": "Beton imalatı",
    "steel_structure": "Çelik konstrüksiyon",
    "electrical_work": "Elektrik tesisatı",
    "hvac_work": "Havalandırma / iklimlendirme",
    "demolition": "Söküm / yıkım (nesne belirsiz)",
    "unknown": "İmalat türü belirlenemedi",
    "multiple": "Birden fazla imalat",
}

TRADE = {
    "gazbeton_wall": "duvar",
    "brick_wall": "duvar",
    "ceramic_surface": "ince_yapi",
    "pvc_floor": "ince_yapi",
    "pvc_profile": "yapi_malzemesi",
    "pvc_pipework": "mekanik_tesisat",
    "pvc_joinery": "dograma",
    "plumbing_tap": "mekanik_tesisat",
    "plumbing_fixture": "mekanik_tesisat",
    "plaster_cement": "ince_yapi",
    "plaster_gypsum": "ince_yapi",
    "plaster_generic": "ince_yapi",
    "cement_surface_coating": "ince_yapi",
    "waterproofing": "yalitim",
    "thermal_insulation": "yalitim",
    "paint": "ince_yapi",
    "window_door": "dograma",
    "concrete_work": "kaba_yapi",
    "steel_structure": "kaba_yapi",
    "electrical_work": "elektrik_tesisati",
    "hvac_work": "mekanik_tesisat",
    "demolition": "sokum",
    "unknown": "belirsiz",
    "multiple": "karma",
}

# Every word below is searched in the text of the actual Excel/PDF entry.
P = {
    "pvc": re.compile(r"\bpvc\b"),
    "gazbeton": re.compile(r"\bgazbeton\w*\b"),
    "tugla": re.compile(r"\btugla\w*\b"),
    "wall": re.compile(r"\b(?:duvar\w*|bolme\w*)\b"),
    "ceramic": re.compile(r"\b(?:seramik\w*|porselen\w*|fayans\w*|karo(?:lar\w*)?|mozaik\w*)\b"),
    "taps": re.compile(r"\b(?:musluk\w*|batarya\w*|salmastra\w*|ara\s+musluk\w*)\b"),
    "fixture": re.compile(r"\b(?:lavabo\w*|klozet\w*|pisuvar\w*|sifon\w*)\b"),
    "floor": re.compile(r"\b(?:zemin\w*|doseme\w*|yer\s+kaplam\w*|taban\w*)\b"),
    "profile": re.compile(r"\b(?:profil\w*|extrud\w*|ekstrud\w*)\b"),
    "pipe": re.compile(r"\b(?:boru\w*|dirsek\w*|pis\s+su\w*|temiz\s+su\w*)\b"),
    "joinery": re.compile(r"\b(?:pencere\w*|kapi\w*|dograma\w*)\b"),
    "plaster": re.compile(r"\bsiva\w*\b"),
    "cement": re.compile(r"\bcimento\w*\b"),
    "gypsum": re.compile(r"\balci\w*\b"),
    "coating": re.compile(r"\b(?:kaplama\w*|kaplan\w*|izolasyon\w*)\b"),
    "waterproof": re.compile(r"\b(?:su\s+yalitim\w*|suyu\s+gecirmez\w*|bitum\w*|membran\w*)\b"),
    "thermal": re.compile(r"\b(?:isi\s+yalitim\w*|mantolama\w*|xps\b|eps\b|tas\s+yunu|cam\s+yunu)\b"),
    "paint": re.compile(r"\b(?:boya\w*|boyan\w*|astar\w*)\b"),
    "electric": re.compile(r"\b(?:elektrik\w*|kablo\w*|priz\w*|sigorta\w*|aydinlatma\w*|trafo\w*)\b"),
    "hvac": re.compile(r"\b(?:havalandirma\w*|klima\w*|fan\w*|kanal\w*)\b"),
    "concrete": re.compile(r"\b(?:betonarme\w*|beton\s+dok\w*|hazir\s+beton\w*|beton\s+imalat\w*)\b"),
    "steel": re.compile(r"\b(?:celik\s+konstruksiyon\w*|celik\s+iskelet\w*)\b"),
    "demolition": re.compile(r"\b(?:sokul\w*|sokum\w*|yikim\w*|yikil\w*|demontaj\w*)\b"),
}

def _hit(name: str, text: str) -> bool:
    return bool(P[name].search(text))


def classify_work(description: str, *, catalog_kind: str | None = None) -> dict:
    """Return a conservative category with explicit signals and review status.

    "Beton, sıva ve benzeri yüzeylere çimento kaplama" is a *coating*, not
    three works; substrate nouns must not masquerade as independent jobs.
    "Seramik salmastralı musluk" is plumbing, not a floor finish.
    """
    plain = normalized(description or "")
    key = "unknown"
    marks: list[str] = []
    reasons: list[str] = []

    def choose(category: str, *signals: str) -> None:
        nonlocal key, marks
        key = category
        marks = [m.group(0) for s in signals if (m := P[s].search(plain))]

    if not plain:
        reasons.append("DESCRIPTION_MISSING")
    elif _hit("gazbeton", plain) and _hit("plaster", plain) and _hit("wall", plain):
        # When wall and plaster are explicitly both mentioned, do not assign
        # the full Excel quantity or one position to the two independent works.
        choose("multiple", "gazbeton", "plaster")
        reasons.append("MULTIPLE_WORK_TYPES")
    elif _hit("taps", plain):
        choose("plumbing_tap", "taps")
    elif _hit("fixture", plain):
        choose("plumbing_fixture", "fixture")
    elif _hit("pvc", plain) and _hit("profile", plain):
        choose("pvc_profile", "pvc", "profile")
    elif _hit("pvc", plain) and _hit("pipe", plain):
        choose("pvc_pipework", "pvc", "pipe")
    elif _hit("pvc", plain) and _hit("joinery", plain):
        choose("pvc_joinery", "pvc", "joinery")
    elif _hit("pvc", plain) and _hit("floor", plain):
        choose("pvc_floor", "pvc", "floor")
    elif _hit("ceramic", plain):
        choose("ceramic_surface", "ceramic")
    elif _hit("gazbeton", plain) and _hit("wall", plain):
        choose("gazbeton_wall", "gazbeton", "wall")
    elif _hit("tugla", plain) and _hit("wall", plain):
        choose("brick_wall", "tugla", "wall")
    elif _hit("waterproof", plain):
        choose("waterproofing", "waterproof")
    elif _hit("thermal", plain):
        choose("thermal_insulation", "thermal")
    elif _hit("cement", plain) and _hit("coating", plain):
        # This rule deliberately precedes "plaster": here sıva may denote
        # the surface on which the coating is applied, not the work itself.
        choose("cement_surface_coating", "cement", "coating")
    elif _hit("plaster", plain) and _hit("cement", plain):
        choose("plaster_cement", "plaster", "cement")
    elif _hit("plaster", plain) and _hit("gypsum", plain):
        choose("plaster_gypsum", "plaster", "gypsum")
    elif _hit("plaster", plain):
        choose("plaster_generic", "plaster")
        reasons.append("PLASTER_BINDER_UNSPECIFIED")
    elif _hit("paint", plain):
        choose("paint", "paint")
    elif _hit("joinery", plain):
        choose("window_door", "joinery")
    elif _hit("electric", plain):
        choose("electrical_work", "electric")
    elif _hit("hvac", plain):
        choose("hvac_work", "hvac")
    elif _hit("steel", plain):
        choose("steel_structure", "steel")
    elif _hit("concrete", plain):
        choose("concrete_work", "concrete")
    elif _hit("demolition", plain):
        choose("demolition", "demolition")
        reasons.append("DEMOLITION_OBJECT_UNSPECIFIED")
    else:
        reasons.append("WORK_OBJECT_UNRECOGNIZED")

    role = (
        "catalog_rayic" if catalog_kind == "rayic" else
        "catalog_poz" if catalog_kind is not None else
        "excel_work_item"
    )
    status = (
        "multiple" if key == "multiple" else
        "unclassified" if key == "unknown" else
        "needs_review" if key in {"plaster_generic", "demolition"} else
        "classified"
    )
    return {
        "version": TAXONOMY_VERSION,
        "class_key": key,
        "label": LABELS[key],
        "trade": TRADE[key],
        "status": status,
        "source_role": role,
        "evidence_terms": marks,
        "review_reasons": reasons,
        "technical_approved": False,
        "auto_match_allowed": False,
        "cost_allowed": False,
    }


def compare_work_classes(excel: dict, pdf: dict) -> list[str]:
    """Fail closed before lexical rank can promote wrong-category positions."""
    if excel["status"] == "multiple":
        return ["EXCEL_MULTIPLE_WORK_CLASSES"]
    if pdf["status"] == "multiple":
        return ["PDF_MULTIPLE_WORK_CLASSES"]
    if excel["class_key"] == "unknown":
        return ["EXCEL_WORK_CLASS_UNVERIFIED"]
    if pdf["class_key"] == "unknown":
        return ["PDF_WORK_CLASS_UNVERIFIED"]
    if excel["class_key"] != pdf["class_key"]:
        return ["WORK_CLASS_MISMATCH"]
    return []
