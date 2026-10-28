
"""ARKEMX M6.0-A.27 - PDF catalog parser.

Pilot implementation for four-column 10.100.xxxx rayic tables.
No database writes or automatic catalog approval.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


POSITION_CODE = re.compile(
    r"^[A-Za-z0-9]+(?:[./_-][A-Za-z0-9]+)*$"
)

TR_PRICE = re.compile(
    r"^(?:\d+|\d{1,3}(?:\.\d{3})+),\d{2}$"
)

RAYIC_CODE = re.compile(r"10\.100\.\d{4}")


@dataclass(frozen=True)
class CatalogRecord:
    code: str
    description: str
    unit: str
    price: Decimal
    source_page: int
    record_type: str
    source_sha256: str


@dataclass(frozen=True)
class ParsedRow:
    code: str
    description: str
    unit: str
    price: Decimal
    source_page: int


def parse_turkish_price(value: str) -> Decimal:
    """Convert Turkish price strings into exact Decimal values."""
    if not isinstance(value, str):
        raise ValueError("Fiyat metin olmalidir")

    raw = value.strip()

    if not TR_PRICE.fullmatch(raw):
        raise ValueError(f"Gecersiz fiyat bicimi: {value}")

    try:
        price = Decimal(
            raw.replace(".", "").replace(",", ".")
        )
    except InvalidOperation as exc:
        raise ValueError("Fiyat ayrıştırılamadı") from exc

    if not price.is_finite() or price <= 0:
        raise ValueError("Fiyat pozitif ve sonlu olmalidir")

    return price


def validate_record(record: CatalogRecord) -> None:
    """Validate a candidate catalog record."""
    if not POSITION_CODE.fullmatch(record.code):
        raise ValueError("Gecersiz poz kodu")

    if len(record.description.strip()) < 3:
        raise ValueError("Eksik poz aciklamasi")

    if not record.unit.strip():
        raise ValueError("Eksik olcu birimi")

    if (
        not isinstance(record.price, Decimal)
        or not record.price.is_finite()
        or record.price <= 0
    ):
        raise ValueError("Gecersiz fiyat")

    if record.source_page < 1:
        raise ValueError("Gecersiz kaynak sayfasi")

    if record.record_type not in {"rayic", "imalat"}:
        raise ValueError("Gecersiz kayit turu")

    if not re.fullmatch(
        r"[a-fA-F0-9]{64}", record.source_sha256
    ):
        raise ValueError("Gecersiz SHA-256")


def parse_position_words(words, source_page: int):
    """Legacy coordinate-based pilot parser.

    Kept for M6.0 and M6.15 regression tests.
    """
    grouped = defaultdict(list)

    for word in words:
        x0, y0, x1, y1, value = word[:5]

        if 40 <= x0 <= 565 and 115 <= y0 <= 775:
            key = round(y0 / 3) * 3
            grouped[key].append((x0, value))

    records = []
    rejected = []

    for y, items in sorted(grouped.items()):
        items.sort(key=lambda item: item[0])

        code = " ".join(
            t for x, t in items if 43 <= x < 105
        )
        description = " ".join(
            t for x, t in items if 105 <= x < 475
        )
        unit = " ".join(
            t for x, t in items if 475 <= x < 515
        )
        raw_price = " ".join(
            t for x, t in items if 515 <= x <= 565
        )

        if not code:
            continue

        try:
            if not POSITION_CODE.fullmatch(code):
                raise ValueError("Gecersiz poz kodu")

            if len(description.strip()) < 3:
                raise ValueError("Eksik aciklama")

            if not unit.strip():
                raise ValueError("Eksik birim")

            price = parse_turkish_price(raw_price)

            records.append(
                ParsedRow(
                    code=code,
                    description=description,
                    unit=unit,
                    price=price,
                    source_page=source_page,
                )
            )

        except ValueError as exc:
            rejected.append({
                "row_y": y,
                "code": code,
                "reason": str(exc),
            })

    return records, rejected


def parse_position_table(page, table, source_page: int):
    """Parse a four-column table with description continuation rows.

    Uses physical PDF cells for word association.
    Rejects malformed records instead of guessing missing values.
    """
    if table.col_count != 4:
        raise ValueError("Beklenmeyen tablo sutun sayisi")

    words = page.get_text("words", sort=True)

    def cell_text(cell):
        if cell is None:
            return ""

        x0, y0, x1, y1 = cell
        selected = []

        for word in words:
            cx = (word[0] + word[2]) / 2
            cy = (word[1] + word[3]) / 2

            if x0 <= cx < x1 and y0 <= cy < y1:
                selected.append(word)

        selected.sort(
            key=lambda w: (round(w[1], 1), w[0])
        )

        return " ".join(w[4] for w in selected).strip()

    records = []
    rejected = []
    seen = set()
    pending = None

    def reject(row, code, reason):
        rejected.append({
            "row": row,
            "code": code,
            "reason": reason,
        })

    def flush_pending():
        nonlocal pending

        if pending is None:
            return

        item = pending
        pending = None

        code = item["code"]

        try:
            description = " ".join(
                part.strip()
                for part in item["parts"]
                if part.strip()
            )

            if code in seen:
                raise ValueError("Tekrarlanan poz kodu")

            if len(description) < 3:
                raise ValueError("Eksik aciklama")

            if not item["unit"].strip():
                raise ValueError("Eksik olcu birimi")

            price = parse_turkish_price(item["price"])

            seen.add(code)

            records.append(
                ParsedRow(
                    code=code,
                    description=description,
                    unit=item["unit"],
                    price=price,
                    source_page=source_page,
                )
            )

        except ValueError as exc:
            reject(item["row"], code, str(exc))

    for row_number, row in enumerate(table.rows, 1):
        if len(row.cells) != 4:
            flush_pending()
            reject(
                row_number, None,
                "Beklenmeyen hucre sayisi"
            )
            continue

        code, description, unit, raw_price = [
            cell_text(cell) for cell in row.cells
        ]

        # A new valid position starts a logical record.
        if RAYIC_CODE.fullmatch(code):
            flush_pending()

            pending = {
                "row": row_number,
                "code": code,
                "parts": [description],
                "unit": unit,
                "price": raw_price,
            }
            continue

        # Skip known table headers.
        if (
            row_number == 1
            and "poz" in code.casefold()
        ):
            flush_pending()
            continue

        # Reject malformed or combined position identities.
        if code and (
            "10.100" in code
            or RAYIC_CODE.search(code)
            or any(ch.isdigit() for ch in code)
        ):
            flush_pending()
            reject(
                row_number, code,
                "Bozuk veya belirsiz poz kimligi"
            )
            continue

        # Other code-column text is not a continuation.
        if code:
            flush_pending()

            if unit or raw_price:
                reject(
                    row_number, code,
                    "Belirsiz satir kimligi"
                )
            # Otherwise treat as a section heading.
            continue

        # A continuation must contain description only.
        if description and not unit and not raw_price:
            if pending is not None:
                pending["parts"].append(description)
            continue

        # Code-free rows containing units or prices
        # cannot be safely associated with another row.
        if unit or raw_price:
            flush_pending()
            reject(
                row_number, None,
                "Belirsiz devam satiri"
            )
            continue

        # Empty row ends the logical record.
        if not any(
            (code, description, unit, raw_price)
        ):
            flush_pending()

    flush_pending()

    # Independent source-code coverage check.
    source_codes = [
        word[4]
        for word in words
        if RAYIC_CODE.fullmatch(word[4])
    ]

    source_counts = Counter(source_codes)
    parsed_counts = Counter(
        record.code for record in records
    )

    for code, count in source_counts.items():
        if count != 1:
            reject(
                None, code,
                "Kaynakta mukerrer poz kodu"
            )

        if parsed_counts[code] != 1:
            reject(
                None, code,
                "Kaynak poz ayrıştırılamadı"
            )

    for code in parsed_counts:
        if code not in source_counts:
            reject(
                None, code,
                "Kaynakta olmayan poz"
            )

    return records, rejected
