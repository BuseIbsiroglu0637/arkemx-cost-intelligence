
"""M6.0-C.3 - Safe PDF table-family classification.

Classifies table structure and detects candidate position codes.

Does not parse prices, approve records or write to a database.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class TableLike(Protocol):
    col_count: int

    def extract(self) -> list[list[str | None]]: ...


@dataclass(frozen=True)
class TableProfile:
    family: str
    column_count: int
    row_count: int
    codes: tuple[str, ...]
    malformed_codes: tuple[str, ...]

    @property
    def duplicate_codes(self) -> tuple[str, ...]:
        counts = Counter(self.codes)
        return tuple(sorted(
            code for code, count in counts.items()
            if count > 1
        ))


DESCRIPTION_HEADERS = frozenset({
    "tanm",
    "tanim",
    "tanimi",
})

PURCHASE_HEADERS = frozenset({
    "satnalmayeri",
    "satinalmayeri",
})


def normalize_header(value: str | None) -> str:
    text = str(value or "")
    text = text.replace("İ", "I").replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)

    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_candidate_code(value: str | None) -> str | None:
    """Recognize a numeric nine-digit position candidate."""

    raw = str(value or "").strip()

    if not re.fullmatch(r"[0-9.\s]+", raw):
        return None

    digits = re.sub(r"\D", "", raw)

    if len(digits) != 9:
        return None

    return (
        f"{digits[:2]}."
        f"{digits[2:5]}."
        f"{digits[5:]}"
    )


def looks_like_malformed_code(value: str | None) -> bool:
    raw = str(value or "").strip()

    return bool(
        re.match(r"^\d{2}[.\s]+\d{3}[.\s]*", raw)
        and parse_candidate_code(raw) is None
    )


def classify_table(table: TableLike) -> TableProfile:
    """Classify PDF table structure without accepting records."""

    rows = table.extract()
    columns = table.col_count

    if not rows:
        return TableProfile(
            family="BELIRSIZ_INCELE",
            column_count=columns,
            row_count=0,
            codes=(),
            malformed_codes=(),
        )

    header = [
        normalize_header(cell)
        for cell in rows[0]
    ]

    codes: list[str] = []
    malformed: list[str] = []

    for row in rows[1:]:
        if not row:
            continue

        raw_code = str(row[0] or "").strip()
        code = parse_candidate_code(raw_code)

        if code is not None:
            codes.append(code)
        elif looks_like_malformed_code(raw_code):
            malformed.append(raw_code)

    has_code_header = (
        len(header) > 0
        and "pozno" in header[0]
    )

    has_description = (
        len(header) > 1
        and header[1] in DESCRIPTION_HEADERS
    )

    has_unit = (
        len(header) > 2
        and "olcubirimi" in header[2]
    )

    def is_price(value: str) -> bool:
        return (
            value.startswith("rayicfiyat")
            or value.startswith("birimfiyat")
        )

    four_columns = (
        columns == 4
        and len(header) == 4
        and has_code_header
        and has_description
        and has_unit
        and is_price(header[3])
    )

    five_columns = (
        columns == 5
        and len(header) == 5
        and has_code_header
        and has_description
        and has_unit
        and header[3] in PURCHASE_HEADERS
        and is_price(header[4])
    )

    duplicates = [
        code
        for code, count in Counter(codes).items()
        if count > 1
    ]

    # Fail closed when identity is malformed or repeated.
    if malformed or duplicates:
        family = "BELIRSIZ_INCELE"

    elif four_columns and codes:
        family = "RAYIC_4_SUTUN_ADAYI"

    elif five_columns and codes:
        family = "RAYIC_5_SUTUN_ADAYI"

    elif columns > 5 and codes:
        family = "KARMASIK_POZ_TABLOSU_INCELE"

    elif codes or four_columns or five_columns:
        family = "BELIRSIZ_INCELE"

    else:
        family = "TEKNIK_VEYA_POZSUZ_TABLO"

    return TableProfile(
        family=family,
        column_count=columns,
        row_count=len(rows),
        codes=tuple(codes),
        malformed_codes=tuple(malformed),
    )


def find_table_overlaps(
    profiles: Sequence[TableProfile],
) -> list[tuple[int, int, tuple[str, ...]]]:
    """Find common codes across tables on the same page.

    Table indices are one-based.
    No automatic merging or deletion.
    """

    overlaps: list[
        tuple[int, int, tuple[str, ...]]
    ] = []

    for i, first in enumerate(profiles):
        for j in range(i + 1, len(profiles)):
            second = profiles[j]

            shared = tuple(sorted(
                set(first.codes) & set(second.codes)
            ))

            if shared:
                overlaps.append((i + 1, j + 1, shared))

    return overlaps
