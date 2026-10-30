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
    r"\b(?:kaba\s*(?:ve|/|\+)\s*ince|ince\s*(?:ve|/|\+)\s*kaba)\s+siva\w*\b"
)
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
    if TOGETHER.search(plain):
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


def plaster_checks(metraj: str, candidate: str) -> tuple[list[str], list[str]]:
    """Return (hard technical contradictions, uncertainties needing review).

    This complements the existing thickness, unit and environment comparisons.
    """
    if not SIVA.search(normalized(metraj)):
        return [], []

    blockers: set[str] = set()
    reviews: set[str] = set()
    left = plaster_stages(metraj)
    right = plaster_stages(candidate)
    if not SIVA.search(normalized(candidate)):
        blockers.add("PLASTER_MATERIAL_MISMATCH")
    elif len(right) > 1 and len(left) == 1:
        # A two-layer PDF scope is not a separately payable one-layer item.
        blockers.add("PLASTER_COMBINED_SCOPE_MISMATCH")
    elif left and right and left != right:
        blockers.add("PLASTER_LAYER_MISMATCH")
    elif left != right:
        reviews.add("PLASTER_LAYER_UNVERIFIED")

    lbind = plaster_binders(metraj)
    rbind = plaster_binders(candidate)
    if lbind and rbind and lbind.isdisjoint(rbind):
        blockers.add("PLASTER_BINDER_MISMATCH")
    elif lbind != rbind:
        reviews.add("PLASTER_BINDER_UNVERIFIED")

    ldose = plaster_dosages(metraj)
    rdose = plaster_dosages(candidate)
    if len(ldose) > 1 or len(rdose) > 1:
        reviews.add("PLASTER_CEMENT_DOSAGE_AMBIGUOUS")
    elif ldose and rdose and ldose != rdose:
        blockers.add("PLASTER_CEMENT_DOSAGE_MISMATCH")
    elif ldose != rdose:
        reviews.add("PLASTER_CEMENT_DOSAGE_UNVERIFIED")

    # Never claim enough source evidence to approve/pluck a rate.
    return sorted(blockers), sorted(reviews)
