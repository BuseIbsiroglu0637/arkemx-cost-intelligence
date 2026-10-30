"""Context-aware measurements in construction descriptions.

Dimensions (60 x 60 cm), tile thickness (8 mm kalınlığında) and
joint width (3 mm derz aralıklı) must never be conflated.
"""
from __future__ import annotations

import re

from .excel import normalized

MEASURE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(mm|cm)\b")
PAIR = re.compile(r"\b(\d{1,4})\s*x\s*(\d{1,4})(?:\s*(?:mm|cm))?\b")
JOINT_AFTER = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*mm\s*(?:['’]?\s*lik\s*)?derz\b")
JOINT_BEFORE = re.compile(
    r"\bderz(?:\s+(?:aralig\w*|boslug\w*|genislig\w*))?\s*(?::|=)?\s*"
    r"(\d+(?:[.,]\d+)?)\s*mm\b"
)
THICKNESS_WORD = re.compile(r"\bkalinlig\w*|\bkalinlik\w*")
TILE_WORD = re.compile(r"\b(?:seramik\w*|porselen\w*|karo(?:s\w*|l\w*|n\w*|d\w*)?)\b")


def extract_measurements(description: str, *, ceramic: bool = False) -> dict:
    text = normalized(description).replace("×", "x")
    dimension_matches = list(PAIR.finditer(text))
    sizes = {tuple(sorted((int(m[1]), int(m[2])))) for m in dimension_matches}
    dimension_spans = [m.span() for m in dimension_matches]
    # Capture only the number spans of joint measurements, including
    # both "3 mm derz aralıklı" and "derz aralığı 3 mm".
    joint_starts = {m.start(1) for pattern in (JOINT_AFTER, JOINT_BEFORE)
                    for m in pattern.finditer(text)}
    thickness: set[float] = set()
    joints: set[float] = set()
    for m in MEASURE.finditer(text):
        # "60 x 60 cm" is a size, never 60 cm of material thickness.
        if any(m.start() < end and m.end() > start for start, end in dimension_spans):
            continue
        value = float(m[1].replace(",", "."))
        if m.start(1) in joint_starts:
            joints.add(round(value, 3))
            continue
        if ceramic:
            # For tiles, generic coating/adhesive measurements cannot be
            # called product thickness without explicit thickness/tile context.
            before = text[max(0, m.start() - 25):m.start()]
            after = text[m.end():m.end() + 36]
            if not (THICKNESS_WORD.search(before) or THICKNESS_WORD.search(after)
                    or TILE_WORD.search(after)):
                continue
        thickness.add(round(value * (10 if m[2] == "cm" else 1), 3))
    return {
        "sizes": sizes,
        "thickness_mm": thickness,
        "joint_width_mm": joints if ceramic else set(),
    }
