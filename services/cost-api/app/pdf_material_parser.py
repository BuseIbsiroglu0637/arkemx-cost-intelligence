
"""M6.0-B.5 - Five-column material catalog parser.

Supports:
- Verified five-column PDF rayic tables
- 10.310.xxxx material positions
- Multiline descriptions
- Turkish decimal prices
- Purchase-place information
- Table headers and material-group headings
- Independent source-code coverage validation

Read-only. No database writes or automatic approvals.
"""

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

from app.pdf_catalog_parser import parse_turkish_price


MATERIAL_CODE = re.compile(r"10\.310\.\d{4}")
SOURCE_CODE = re.compile(r"10\.\d{3}\.\d{4}")


@dataclass(frozen=True)
class MaterialParsedRow:
    code: str
    description: str
    unit: str
    purchase_place: str
    price: Decimal
    source_page: int


class PendingMaterial(TypedDict):
    row: int
    code: str
    parts: list[str]
    unit: str
    place: str
    price: str


class RejectedMaterialRow(TypedDict):
    row: int | None
    code: str | None
    reason: str


def parse_material_table(
    page,
    table,
    source_page: int,
) -> tuple[list[MaterialParsedRow], list[RejectedMaterialRow]]:
    """Parse a verified five-column material rayic table."""

    if table.col_count != 5:
        raise ValueError("Beklenmeyen tablo sutun sayisi")

    if source_page < 1:
        raise ValueError("Gecersiz kaynak sayfasi")

    words = page.get_text("words", sort=True)

    def inside(word, bbox) -> bool:
        x = (word[0] + word[2]) / 2
        y = (word[1] + word[3]) / 2

        return (
            bbox[0] <= x < bbox[2]
            and bbox[1] <= y < bbox[3]
        )

    def cell_text(cell) -> str:
        if cell is None:
            return ""

        selected = [
            word
            for word in words
            if inside(word, cell)
        ]

        selected.sort(
            key=lambda word: (
                round(word[1], 1),
                word[0],
            )
        )

        return " ".join(
            word[4] for word in selected
        ).strip()

    def compact_text(value: str) -> str:
        """Normalize a table header for recognition."""
        return "".join(
            char
            for char in value.casefold()
            if char.isalnum()
        )

    records: list[MaterialParsedRow] = []
    rejected: list[RejectedMaterialRow] = []
    seen: set[str] = set()
    pending: PendingMaterial | None = None

    def reject(
        row: int | None,
        code: str | None,
        reason: str,
    ) -> None:
        rejected.append({
            "row": row,
            "code": code,
            "reason": reason,
        })

    def flush_pending() -> None:
        nonlocal pending

        if pending is None:
            return

        item = pending
        pending = None

        code = item["code"]

        try:
            description = " ".join(
                " ".join(item["parts"]).split()
            )

            if code in seen:
                raise ValueError(
                    "Tekrarlanan poz kodu"
                )

            if len(description) < 3:
                raise ValueError(
                    "Eksik malzeme aciklamasi"
                )

            if not item["unit"].strip():
                raise ValueError(
                    "Eksik olcu birimi"
                )

            if not item["place"].strip():
                raise ValueError(
                    "Eksik satin alma yeri"
                )

            price = parse_turkish_price(
                item["price"]
            )

            record = MaterialParsedRow(
                code=code,
                description=description,
                unit=item["unit"].strip(),
                purchase_place=item["place"].strip(),
                price=price,
                source_page=source_page,
            )

            records.append(record)
            seen.add(code)

        except ValueError as exc:
            reject(
                item["row"],
                code,
                str(exc),
            )

    for row_number, row in enumerate(
        table.rows,
        start=1,
    ):
        if len(row.cells) != 5:
            flush_pending()

            reject(
                row_number,
                None,
                "Beklenmeyen hucre sayisi",
            )
            continue

        code, description, unit, place, raw_price = [
            cell_text(cell)
            for cell in row.cells
        ]

        # A verified material position starts a new record.
        if MATERIAL_CODE.fullmatch(code):
            flush_pending()

            pending = {
                "row": row_number,
                "code": code,
                "parts": [description],
                "unit": unit,
                "place": place,
                "price": raw_price,
            }
            continue

        # Non-position text in the first column can be
        # a table header or a standalone material heading.
        if code:
            normalized_code = compact_text(code)
            normalized_desc = compact_text(description)
            normalized_price = compact_text(raw_price)

            is_table_header = (
                row_number == 1
                and "pozno" in normalized_code
                and "tan" in normalized_desc
                and "fiyat" in normalized_price
            )

            is_section_heading = (
                not any(
                    (
                        description.strip(),
                        unit.strip(),
                        place.strip(),
                        raw_price.strip(),
                    )
                )
                and not any(
                    char.isdigit()
                    for char in code
                )
                and len(code.split()) >= 2
            )

            flush_pending()

            if is_table_header or is_section_heading:
                # These are not position records.
                # Group context is not yet persisted.
                continue

            # Unknown numeric or malformed identities
            # must remain rejected.
            reject(
                row_number,
                code,
                "Beklenmeyen poz kimligi",
            )
            continue

        # Description-only continuation row.
        if (
            description
            and not unit
            and not place
            and not raw_price
        ):
            if pending is not None:
                pending["parts"].append(description)

            continue

        # A row without a code must not introduce
        # another unit, purchase place or price.
        if unit or place or raw_price:
            flush_pending()

            reject(
                row_number,
                None,
                "Belirsiz devam satiri",
            )
            continue

        # Empty physical row.
        if not any(
            (code, description, unit, place, raw_price)
        ):
            flush_pending()

    flush_pending()

    # Independent source-code coverage check.
    source_codes: list[str] = [
        word[4]
        for word in words
        if inside(word, table.bbox)
        and SOURCE_CODE.fullmatch(word[4])
    ]

    source_counts = Counter(source_codes)

    parsed_counts = Counter(
        record.code
        for record in records
    )

    for code, count in source_counts.items():
        if count != 1:
            reject(
                None,
                code,
                "Kaynakta mukerrer poz kodu",
            )

        if not MATERIAL_CODE.fullmatch(code):
            reject(
                None,
                code,
                "Desteklenmeyen poz ailesi",
            )

        if parsed_counts[code] != 1:
            reject(
                None,
                code,
                "Kaynak poz ayrıştırılamadı",
            )

    # Reject identities not present in the source.
    for code in parsed_counts:
        if code not in source_counts:
            reject(
                None,
                code,
                "Kaynakta olmayan poz",
            )

    return records, rejected
