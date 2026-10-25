"""M4-v0.1: reproducible, non-generative construction specification comparison.

Deterministic rule decisions are NOT a warranty of technical compliance. A
high lexical score cannot override a critical dimensional/material conflict.
"""
import re
from .matching import similarity
from .excel import normalized

VERSION = "technical-rules-v0.1"
MATERIAL_ALIASES = {
    "gazbeton": (r"\bgazbeton\b",),
    "seramik": (r"\bseramik\b", r"\bporselen\b"),
    "beton": (r"\bbeton\b",),
    "tugla": (r"\btugla\b",),
    "boya": (r"\bboya\b", r"\bboyama\b"),
    "celik": (r"\bcelik\b",),
    "kapi": (r"\bkapi\b",),
    "siva": (r"\bsiva\b",),
    "yalitim": (r"\byalitim\b",),
    "cam": (r"\bcam\b",),
}
SURFACES = {
    "zemin": (r"\bzemin\b", r"\bdoseme\b"),
    "duvar": (r"\bduvar\b",),
    "tavan": (r"\btavan\b",),
}
METHODS = {
    "sokum": (r"\bsokum\b", r"\bsokme\b", r"\bdemontaj\b"),
    "montaj": (r"\bmontaj\b", r"\btakilmasi\b", r"\bkurulum\b"),
    "dokum": (r"\bdokum\b", r"\bdokulmesi\b"),
    "kaplama": (r"\bkaplama\b", r"\bkaplanmasi\b"),
    "boyama": (r"\bboyama\b", r"\bboya\s+isleri\b"),
    "orulme": (r"\borulmesi\b", r"\borulme\b", r"\borgu\b"),
}
ENVIRONMENTS = {"ic": (r"\bic\b",), "dis": (r"\bdis\b", r"\bcephe\b")}
THICKNESS = re.compile(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(mm|cm)\b")
DIMENSIONS = re.compile(r"\b(\d{1,4})\s*x\s*(\d{1,4})\b")


def _attribute(text: str, dictionary: dict[str, tuple[str, ...]]) -> str | None:
    for label, patterns in dictionary.items():
        if any(re.search(pattern, text) for pattern in patterns):
            return label
    return None


def extract(description: str, unit: str | None = None) -> dict:
    text = normalized(description).replace("×", "x")
    mat = _attribute(text, MATERIAL_ALIASES)
    surface = _attribute(text, SURFACES)
    method = _attribute(text, METHODS)
    environment = _attribute(text, ENVIRONMENTS)
    match = THICKNESS.search(text)
    thickness_mm = None
    if match:
        value = float(match.group(1).replace(",", "."))
        thickness_mm = round(value * (10 if match.group(2) == "cm" else 1), 2)
    sizes = {tuple(sorted((int(a), int(b)))) for a, b in DIMENSIONS.findall(text)}
    return {
        "material": mat,
        "surface": surface,
        "method": method,
        "environment": environment,
        "thickness_mm": thickness_mm,
        "dimensions": sorted([list(pair) for pair in sizes]),
        "unit": unit,
    }


def compare(description: str, unit: str | None,
            catalog_description: str, catalog_unit: str | None,
            *, quantity_known: bool = True, review_required: bool = False) -> dict:
    """Fail closed: unknown essential attributes require qualified expert review."""
    left = extract(description, unit)
    right = extract(catalog_description, catalog_unit)
    fields = []
    blockers = []
    reviews = []
    matches = []
    for key, title, essential in (
        ("unit", "Ölçü birimi", True),
        ("material", "Malzeme", True),
        ("thickness_mm", "Kalınlık (mm)", False),
        ("dimensions", "Ebatlar", False),
        ("surface", "Uygulama yüzeyi", False),
        ("method", "Uygulama yöntemi", False),
        ("environment", "İç/dış ortam", False),
    ):
        a, b = left[key], right[key]
        missing_a = a is None or a == []
        missing_b = b is None or b == []
        if missing_a and missing_b:
            status = "review" if essential else "not_specified"
        elif missing_a or missing_b:
            status = "review"
        elif a != b:
            status = "block"
        else:
            status = "match"
        if status == "block":
            blockers.append(key.upper() + "_MISMATCH")
        elif status == "review":
            reviews.append(key.upper() + "_UNVERIFIED")
        elif status == "match":
            matches.append(key.upper() + "_MATCH")
        fields.append({
            "key": key, "label": title,
            "metraj": a, "catalog": b,
            "status": status,
            "reason": (
                "Farklı teknik değerler: onay engelli" if status == "block"
                else "Tariflerden en az birinde bilgi eksik" if status == "review"
                else "Değerler aynı" if status == "match"
                else "Tariflerde belirtilmemiş; kapsam ayrıca incelenmeli"
            ),
        })

    if review_required or not quantity_known:
        blockers.append("METRAJ_REVIEW_REQUIRED")
    blockers = sorted(set(blockers))
    reviews = sorted(set(reviews))
    status = "blocked" if blockers else ("review" if reviews else "compatible")
    return {
        "version": VERSION,
        "status": status,
        "manual_approval_allowed": status == "compatible",
        "blockers": blockers,
        "review_flags": reviews,
        "matches": sorted(set(matches)),
        "fields": fields,
        "metraj_excerpt": description[:500],
        "catalog_excerpt": catalog_description[:500],
        "lexical_similarity": similarity(description, catalog_description),
        "score_is_probability": False,
    }
