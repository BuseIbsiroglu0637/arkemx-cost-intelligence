"""A3.5 - Preserve explicitly named layers without thickness.

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
    thickness_mm: Decimal | None
    work_type: str | None
    materials: tuple[str, ...]
    quote: str
    start: int
    end: int


def fold(text: str) -> str:
    """Normalize Turkish characters for matching."""
    return text.translate(TRANSLATION).lower()


WORK_MENTION = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in WORK_TYPES)
)

NEGATED_APPLICATION = re.compile(
    r"^\s*(?:(?:yapilmasi|uygulanmasi)\s+)?"
    r"(?:haric(?:tir)?|dahil\s+degil(?:dir)?|kapsam\s+disi(?:dir)?|"
    r"yapilmayacak(?:tir)?|uygulanmayacak(?:tir)?|"
    r"yapilmamasi|uygulanmamasi|yok(?:tur)?)\b"
)

NEGATION_WORD = re.compile(
    r"\b(?:haric(?:tir)?|degil(?:dir)?|yapilmayacak(?:tir)?|"
    r"uygulanmayacak(?:tir)?|yapilmamasi|uygulanmamasi|yok(?:tur)?|"
    r"kapsam\s+disi(?:dir)?)\b"
)


def _clause_work_scopes(clause: str) -> list[tuple[str, str]]:
    """Classify a narrow application grammar; unresolved scope stays unknown."""
    mentions = list(WORK_MENTION.finditer(clause))
    result = []
    for index, mention in enumerate(mentions):
        end = mentions[index + 1].start() if index + 1 < len(mentions) else len(clause)
        suffix = clause[mention.end():end]
        negative = NEGATED_APPLICATION.match(suffix)
        if negative:
            remainder = suffix[negative.end():]
            # Do not turn a double negation or conflicting instruction into fact.
            conflict = re.search(
                r"\b(?:degil(?:dir)?|yapilacak(?:tir)?|uygulanacak(?:tir)?)\b",
                remainder,
            )
            state = "unknown" if conflict else "excluded"
        elif NEGATION_WORD.search(suffix):
            # An intervening object can own the exclusion, e.g. boya haric.
            unrelated = re.search(
                r"\b(?:boya|malzeme)\s+(?:haric(?:tir)?|dahil\s+degil(?:dir)?)\b",
                suffix,
            )
            state = "included" if unrelated and len(mentions) == 1 else "unknown"
        elif len(mentions) > 1 and NEGATION_WORD.search(clause):
            state = "unknown"
        else:
            state = "included"
        result.append((mention.lastgroup, state))
    return result


def extract_work_scopes(description: str) -> dict[str, list[dict]]:
    """Keep application scope with original-text evidence, including exclusions."""
    normalized = fold(description)
    if len(normalized) != len(description):
        raise ValueError("Normalization changed source offsets")
    result: dict[str, list[dict]] = {}
    start = 0
    spans = []
    for separator in CLAUSE_BOUNDARY.finditer(normalized):
        spans.append((start, separator.start()))
        start = separator.end()
    spans.append((start, len(description)))
    for start, end in spans:
        while start < end and description[start].isspace():
            start += 1
        while end > start and description[end - 1].isspace():
            end -= 1
        for work_type, state in _clause_work_scopes(normalized[start:end]):
            result.setdefault(work_type, []).append({
                "value": state,
                "evidence": {
                    "quote": description[start:end],
                    "start": start,
                    "end": end,
                    "offset_basis": "original_text",
                },
            })
    return result


def extract_layer_measurements(
    description: str,
) -> tuple[LayerMeasurement, ...]:
    """Extract measured applications and explicitly named unmeasured layers.

    Source offsets refer to the original input string.

    Material and work-type associations are extracted only when a clause
    contains one measurement or one explicitly named unmeasured application.
    Multiple measurements in the same
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
        scopes = _clause_work_scopes(clause)
        # Excluded or unresolved applications never become positive layers,
        # even when their clause contains a thickness measurement.
        if any(state != "included" for _, state in scopes):
            continue

        # A named application can exist even when its thickness is absent.
        # Keep its original clause so dosage ownership remains source-backed.
        if not matches:
            work_pattern = "|".join(
                f"(?:{pattern})" for _, pattern in WORK_TYPES
            )
            mentions = list(re.finditer(work_pattern, clause))
            if not mentions:
                continue

            work_type = None
            materials = ()
            if len(mentions) == 1:
                work_type = next(
                    name for name, pattern in WORK_TYPES
                    if re.fullmatch(pattern, mentions[0].group())
                )
                materials = tuple(
                    name for name, pattern in MATERIALS
                    if re.search(pattern, clause)
                )

            quote_start = clause_start
            quote_end = clause_end
            while quote_start < quote_end and description[quote_start].isspace():
                quote_start += 1
            while quote_end > quote_start and description[quote_end - 1].isspace():
                quote_end -= 1

            results.append(
                LayerMeasurement(
                    order=len(results) + 1,
                    thickness_mm=None,
                    work_type=work_type,
                    materials=materials,
                    quote=description[quote_start:quote_end],
                    start=quote_start,
                    end=quote_end,
                )
            )
            continue

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
