"""M4-v0.1: reproducible, non-generative construction specification comparison.

Deterministic rule decisions are NOT a warranty of technical compliance. A
high lexical score cannot override a critical dimensional/material conflict.
"""
import re
from .matching import similarity
from .measurement_context import extract_measurements
from .excel import normalized

VERSION = "technical-rules-v0.4"
MATERIAL_ALIASES = {
    "gazbeton": (r"\bgazbeton\b",),
    "seramik": (r"\bseramik\w*\b", r"\bporselen\w*\b", r"\bkaro(?:s\w*|l\w*|n\w*|d\w*)?\b", r"\bfayans\w*\b"),
    "poliuretan": (r"\bpoliuretan\w*\b",),
    "epoksi": (r"\bepoksi\w*\b",),
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
# Parse explicit masonry properties in either Unicode- or ASCII-superscript units.
# Do not infer a default density/strength when the metraj omits them.
GAZBETON_STRENGTH = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*n\s*/\s*mm(?:2|²)(?!\w)")
GAZBETON_DENSITY = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*kg\s*/\s*m(?:3|³)(?!\w)")


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
    measurements = extract_measurements(description, ceramic=mat == "seramik")
    thick_values = measurements["thickness_mm"]
    joint_values = measurements["joint_width_mm"]
    # Conflicting measurements are ambiguous and cannot be silently resolved.
    thickness_mm = next(iter(thick_values)) if len(thick_values) == 1 else None
    joint_width_mm = next(iter(joint_values)) if len(joint_values) == 1 else None
    sizes = measurements["sizes"]
    # Only expose gazbeton-specific attributes for gazbeton, not concrete or other works.
    strength = GAZBETON_STRENGTH.search(text) if mat == "gazbeton" else None
    density = GAZBETON_DENSITY.search(text) if mat == "gazbeton" else None
    return {
        "material": mat,
        "surface": surface,
        "method": method,
        "environment": environment,
        "thickness_mm": thickness_mm,
        "joint_width_mm": joint_width_mm,
        "dimensions": sorted([list(pair) for pair in sizes]),
        "unit": unit,
        "gazbeton_strength_n_mm2": float(strength.group(1).replace(",", ".")) if strength else None,
        "gazbeton_density_kg_m3": float(density.group(1).replace(",", ".")) if density else None,
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
        ("thickness_mm", "Ürün kalınlığı (mm)", False),
        ("joint_width_mm", "Derz aralığı (mm)", False),
        ("dimensions", "Ebatlar", False),
        ("surface", "Uygulama yüzeyi", False),
        ("method", "Uygulama yöntemi", False),
        ("environment", "İç/dış ortam", False),
        ("gazbeton_strength_n_mm2", "Gazbeton dayanımı (N/mm²)", False),
        ("gazbeton_density_kg_m3", "Gazbeton yoğunluğu (kg/m³)", False),
    ):
        a, b = left[key], right[key]
        missing_a = a is None or a == []
        missing_b = b is None or b == []
        if key == "joint_width_mm" and missing_a:
            # PDF may describe its standard grout spacing even when the
            # metraj leaves grout choice open. Don't mislabel this as a
            # missing tile-thickness requirement. If metraj explicitly
            # requires a width, a mismatch blocks and missing PDF width
            # still requires review.
            status = "not_specified"
        elif missing_a and missing_b:
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

    # When a ceramic finish is explicit, an unspecified/non-ceramic finish
    # on the candidate is not a sufficient material match. Keep it in review;
    # explicit opposing finishes are already blocked by MATERIAL_MISMATCH.
    if left["material"] == "seramik" and right["material"] is None:
        reviews.append("CERAMIC_FINISH_UNVERIFIED")
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
