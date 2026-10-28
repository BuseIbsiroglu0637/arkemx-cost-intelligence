
"""M6.0-D.3 - Safe PDF table-family classification.

Classifies PDF table structures and detects position-code candidates.

Supports:
- 3-column rate tables
- 4-column rate tables
- 5-column material rate tables
- 4-column installation price tables
- Complex and technical tables

Does not approve records, parse final prices, infer units,
modify PDFs, or write to a database.
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

        return tuple(
            sorted(
                code
                for code, count in counts.items()
                if count > 1
            )
        )


DESCRIPTION_HEADERS = frozenset({
    "tanm",
    "tanim",
    "tanimi",
})

PURCHASE_HEADERS = frozenset({
    "satnalmayeri",
    "satinalmayeri",
})

PRICE_HEADERS = frozenset({
    "rayicfiyattl",
    "rayicfiyatitl",
    "rayicfiyati",
    "birimfiyattl",
    "birimfiyati",
    "birimfiyat",
})

INSTALLATION_DESCRIPTION_HEADERS = frozenset({
    "yapilacakisincinsi",
})

INSTALLATION_PRICE_HEADERS = frozenset({
    "montajlibirimfiyattl",
})

INSTALLATION_LABOR_HEADERS = frozenset({
    "montajbedelitl",
})


def normalize_header(value: str | None) -> str:
    """Normalize observed PDF header text safely."""

    text = str(value or "")

    text = text.replace("İ", "I").replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)

    return re.sub(
        r"[^a-z0-9]",
        "",
        text.lower(),
    )


def parse_candidate_code(
    value: str | None,
) -> str | None:
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


def looks_like_malformed_code(
    value: str | None,
) -> bool:
    """Flag broken codes that resemble position identifiers."""

    raw = str(value or "").strip()

    return bool(
        re.match(
            r"^\d{2}[.\s]+\d{3}[.\s]*",
            raw,
        )
        and parse_candidate_code(raw) is None
    )


def is_price_header(value: str) -> bool:
    """Accept only explicitly recognized price-header forms."""

    return value in PRICE_HEADERS


def classify_table(table: TableLike) -> TableProfile:
    """Classify a table without approving or importing records."""

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
        and header[2] == "olcubirimi"
    )

    # -----------------------------------------
    # M6.0-C.3 - Existing four-column rate
    # -----------------------------------------

    four_columns = (
        columns == 4
        and len(header) == 4
        and has_code_header
        and has_description
        and has_unit
        and is_price_header(header[3])
    )

    # -----------------------------------------
    # M6.0-C.3 - Existing five-column rate
    # -----------------------------------------

    five_columns = (
        columns == 5
        and len(header) == 5
        and has_code_header
        and has_description
        and has_unit
        and header[3] in PURCHASE_HEADERS
        and is_price_header(header[4])
    )

    # -----------------------------------------
    # M6.0-D.3 - Three-column rate
    #
    # Columns:
    # Poz No / Description / Rate
    #
    # The unit is NOT present in this family.
    # -----------------------------------------

    three_column_rate = (
        columns == 3
        and len(header) == 3
        and has_code_header
        and has_description
        and is_price_header(header[2])
    )

    # -----------------------------------------
    # M6.0-D.3 - Four-column installation
    #
    # Columns:
    # Poz No / Work Description /
    # Installed Unit Price / Installation Cost
    #
    # The two price fields must remain distinct.
    # -----------------------------------------

    four_column_installation = (
        columns == 4
        and len(header) == 4
        and has_code_header
        and header[1] in INSTALLATION_DESCRIPTION_HEADERS
        and header[2] in INSTALLATION_PRICE_HEADERS
        and header[3] in INSTALLATION_LABOR_HEADERS
    )

    # -----------------------------------------
    # Identity safety checks
    # -----------------------------------------

    duplicates = [
        code
        for code, count in Counter(codes).items()
        if count > 1
    ]

    # Never automatically accept a table with
    # malformed or repeated position identities.

    if malformed or duplicates:
        family = "BELIRSIZ_INCELE"

    # Existing supported families.

    elif four_columns and codes:
        family = "RAYIC_4_SUTUN_ADAYI"

    elif five_columns and codes:
        family = "RAYIC_5_SUTUN_ADAYI"

    # New M6.0-D.3 families.

    elif three_column_rate and codes:
        family = "RAYIC_3_SUTUN_ADAYI"

    elif four_column_installation and codes:
        family = "MONTAJ_4_SUTUN_ADAYI"

    # Complex layouts require further review.

    elif columns > 5 and codes:
        family = "KARMASIK_POZ_TABLOSU_INCELE"

    # Any unresolved position-bearing structure
    # must remain in the review category.

    elif (
        codes
        or four_columns
        or five_columns
        or three_column_rate
        or four_column_installation
    ):
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
    """Find shared codes between tables on the same page.

    Table indices are one-based.

    This function never merges or deletes records.
    """

    overlaps: list[
        tuple[int, int, tuple[str, ...]]
    ] = []

    for i, first in enumerate(profiles):
        for j in range(i + 1, len(profiles)):
            second = profiles[j]

            shared = tuple(
                sorted(
                    set(first.codes)
                    & set(second.codes)
                )
            )

            if shared:
                overlaps.append(
                    (i + 1, j + 1, shared)
                )

    return overlaps
