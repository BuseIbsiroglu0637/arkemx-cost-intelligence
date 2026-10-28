"""A1.2 - Source-backed technical layer extraction.

Pilot for wall and plaster descriptions.
Preserves material context before and after measurements.
Does not decide engineering compatibility or extract mortar dosage.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

TRANSLATION = str.maketrans({
    "İ": "i",
    "I": "i",
    "ı": "i",
    "ç": "c",
    "Ç": "c",
    "ğ": "g",
    "Ğ": "g",
    "ö": "o",
    "Ö": "o",
    "ş": "s",
    "Ş": "s",
    "ü": "u",
    "Ü": "u",
})

THICKNESS = re.compile(
    r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(mm|cm)\b"
)

# Split explicit clauses without splitting decimal commas.
CLAUSE_BOUNDARY = re.compile(
    r"\buzerine\b|;|(?<!\d),|,(?!\d)"
)

WORK_TYPES = (
    ("kaba_siva", r"\bkaba\s+siva\b"),
    ("ince_siva", r"\bince\s+siva\b"),
    ("gazbeton_duvar", r"\bgazbeton\s+duvar\b"),
    ("siva", r"\bsiva\b"),
)

MATERIALS = (
    ("gazbeton", r"\bgazbeton\b"),
    ("cimento", r"\bcimento\b"),
    ("alci", r"\balci\b"),
)


@dataclass(frozen=True)
class LayerMeasurement:
    order: int
    thickness_mm: Decimal
    work_type: str | None
    materials: tuple[str, ...]
    quote: str
    start: int
    end: int


def fold(text: str) -> str:
    """Normalize Turkish characters for matching."""
    return text.translate(TRANSLATION).lower()


def extract_layer_measurements(
    description: str,
) -> tuple[LayerMeasurement, ...]:
    """Extract measurements inside explicitly separated clauses.

    Source offsets refer to the original input string.

    Material and work-type associations are extracted only when a clause
    contains exactly one measurement. Multiple measurements in the same
    clause remain unresolved rather than being assigned by guesswork.

    Unknown work types remain None. These records do not grant technical
    compatibility or engineering approval.
    """

    normalized = fold(description)

    if len(normalized) != len(description):
        raise ValueError("Normalization changed source offsets")

    spans: list[tuple[int, int]] = []
    start = 0

    for separator in CLAUSE_BOUNDARY.finditer(normalized):
        spans.append((start, separator.start()))
        start = separator.end()

    spans.append((start, len(description)))

    results: list[LayerMeasurement] = []

    for clause_start, clause_end in spans:
        clause = normalized[clause_start:clause_end]
        matches = list(THICKNESS.finditer(clause))

        for match in matches:
            value = Decimal(
                match.group(1).replace(",", ".")
            )
            factor = (
                Decimal("10")
                if match.group(2) == "cm"
                else Decimal("1")
            )

            work_type: str | None = None
            materials: tuple[str, ...] = ()

            # For unresolved associations, cite only the measurement.
            quote_start = clause_start + match.start()
            quote_end = clause_start + match.end()

            if len(matches) == 1:
                for name, pattern in WORK_TYPES:
                    if re.search(pattern, clause):
                        work_type = name
                        break

                materials = tuple(
                    name
                    for name, pattern in MATERIALS
                    if re.search(pattern, clause)
                )

                # Include material descriptions before the measurement.
                quote_start = clause_start
                quote_end = clause_end

                while (
                    quote_start < quote_end
                    and description[quote_start].isspace()
                ):
                    quote_start += 1

                while (
                    quote_end > quote_start
                    and description[quote_end - 1].isspace()
                ):
                    quote_end -= 1

            results.append(
                LayerMeasurement(
                    order=len(results) + 1,
                    thickness_mm=value * factor,
                    work_type=work_type,
                    materials=materials,
                    quote=description[quote_start:quote_end],
                    start=quote_start,
                    end=quote_end,
                )
            )

    return tuple(results)