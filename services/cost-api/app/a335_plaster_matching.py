"""A3.35 — conservative plaster-stage/recipe check against authentic PDF poz text.

This does not infer unknown layer, harc, or cement dosage. Explicitly mixed
kaba+ince poz is NOT a one-layer poz and must not be separately priced twice.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .excel import normalized

SIVA = re.compile(r"\bsiva\w*\b")
LAYER_BEFORE = re.compile(
    r"\b(kaba|ince)\s+(?:\w+\s+)?siva\w*\b"
)
LAYER_AFTER = re.compile(
    r"\bsiva\w*\s+(?:katmani\s+)?(kaba|ince)\b"
)
TOGETHER = re.compile(
    r"\b(?:kaba\s*(?:ve|/|\+)\s*ince|ince\s*(?:ve|/|\+)\s*kaba)"
    r"\s+(?:(?:\w+\s+){0,5})?(?:siva\w*|harc\w*)\b"
)
# A 2026 official poz can describe two application stages through its mortar
# types rather than explicitly saying "kaba sıva + ince sıva".
MORTAR_STAGE = re.compile(r"\b(kaba|ince)\s+harc\w*\b")
ON_TOP = re.compile(
    r"\bkaba\s+siva\w*.{0,550}\buzerine\b.{0,300}"
    r"\bserpme\s*(?:\(carpma\)\s*)?siva\w*\b",
    re.DOTALL,
)
# Known 2026 YFK two-layer plaster works, independently published as *one*
# combined square-metre poz. Never apply them to each separately measured layer.
KNOWN_2026_COMBINED_POZ = frozenset({
    "15.275.1111", "15.275.1112", "15.275.1113", "15.275.1114",
})
CEMENT_DOSAGE = re.compile(
    r"(?<!\w)(\d+(?:[.,]\d+)?)\s*kg\s+cimento\s+dozlu\b"
)
BINDERS = (
    ("cimento", re.compile(r"\bcimento\w*\b")),
    ("alci", re.compile(r"\balci\w*\b")),
    ("kirec", re.compile(r"\bkirec\w*\b")),
)


def plaster_stages(description: str) -> frozenset[str]:
    plain = normalized(description)
    if not SIVA.search(plain):
        return frozenset()
    found = {match[1] for match in LAYER_BEFORE.finditer(plain)}
    found.update(match[1] for match in LAYER_AFTER.finditer(plain))
    found.update(match[1] for match in MORTAR_STAGE.finditer(plain))
    if TOGETHER.search(plain) or ON_TOP.search(plain):
        found.update(("kaba", "ince"))
    return frozenset(found)


def plaster_binders(description: str) -> frozenset[str]:
    plain = normalized(description)
    return frozenset(name for name, pattern in BINDERS if pattern.search(plain))


def plaster_dosages(description: str) -> frozenset[Decimal]:
    """Only recognize explicit 'kg çimento dozlu' values, not ungrounded kg claims."""
    plain = normalized(description)
    return frozenset(
        Decimal(match[1].replace(",", "."))
        for match in CEMENT_DOSAGE.finditer(plain)
    )


def plaster_checks(
    metraj: str, candidate: str, *,
    scope: str = "", position_code: str = "",
) -> tuple[list[str], list[str]]:
    """Return (hard technical contradictions, uncertainties needing review).

    This complements the existing thickness, unit and environment comparisons.
    """
    if not SIVA.search(normalized(metraj)):
        return [], []

    blockers: set[str] = set()
    reviews: set[str] = set()
    left = plaster_stages(metraj)
    title_stages = plaster_stages(candidate)
    scope_stages = plaster_stages(scope) if scope else frozenset()
    all_stages = title_stages | scope_stages
    if not SIVA.search(normalized(candidate)) and not SIVA.search(normalized(scope)):
        blockers.add("PLASTER_MATERIAL_MISMATCH")
    elif len(left) == 1 and (
        len(all_stages) > 1 or position_code in KNOWN_2026_COMBINED_POZ
    ):
        # A composite price is not a separately payable single-layer rate.
        # Trust both the actual PDF text and the verified 2026 position identity.
        blockers.add("PLASTER_COMBINED_SCOPE_MISMATCH")
    elif title_stages and scope_stages and title_stages != scope_stages:
        # PDF title and its own scope disagree: never silently choose a layer.
        blockers.add("PLASTER_SCOPE_CONFLICT")
    elif left and all_stages and left != all_stages:
        blockers.add("PLASTER_LAYER_MISMATCH")
    elif left != all_stages:
        reviews.add("PLASTER_LAYER_UNVERIFIED")

    lbind = plaster_binders(metraj)
    rbind = plaster_binders(candidate) | (plaster_binders(scope) if scope else frozenset())
    if lbind and rbind and lbind.isdisjoint(rbind):
        blockers.add("PLASTER_BINDER_MISMATCH")
    elif lbind != rbind:
        reviews.add("PLASTER_BINDER_UNVERIFIED")

    ldose = plaster_dosages(metraj)
    rdose = plaster_dosages(candidate) | (plaster_dosages(scope) if scope else frozenset())
    if len(ldose) > 1 or len(rdose) > 1:
        reviews.add("PLASTER_CEMENT_DOSAGE_AMBIGUOUS")
    elif ldose and rdose and ldose != rdose:
        blockers.add("PLASTER_CEMENT_DOSAGE_MISMATCH")
    elif ldose != rdose:
        reviews.add("PLASTER_CEMENT_DOSAGE_UNVERIFIED")

    # Never claim enough source evidence to approve/pluck a rate.
    return sorted(blockers), sorted(reviews)
