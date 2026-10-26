import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from collections import defaultdict

POSITION_CODE = re.compile(
    r"^[A-Za-z0-9]+(?:[./_-][A-Za-z0-9]+)*$"
)

TR_PRICE = re.compile(
    r"^\d{1,3}(?:\.\d{3})*,\d{2}$"
)

def parse_turkish_price(value: str) -> Decimal:
    """TÃ¼rkÃ§e para biÃ§imini gÃ¼venli ÅŸekilde Decimal deÄŸerine dÃ¶nÃ¼ÅŸtÃ¼rÃ¼r."""
    if not isinstance(value, str):
        raise ValueError("Fiyat metin olmalÄ±dÄ±r")

    raw = value.strip()

    if not TR_PRICE.fullmatch(raw):
        raise ValueError(f"GeÃ§ersiz fiyat biÃ§imi: {value}")

    try:
        result = Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Fiyat ayrÄ±ÅŸtÄ±rÄ±lamadÄ±") from exc

    if not result.is_finite() or result <= 0:
        raise ValueError("Fiyat pozitif olmalÄ±dÄ±r")

    return result


@dataclass(frozen=True)
class CatalogRecord:
    code: str
    description: str
    unit: str
    price: Decimal
    source_page: int
    record_type: str
    source_sha256: str


def validate_record(record: CatalogRecord) -> None:
    """Validate catalog fields without importing any data."""
    if not POSITION_CODE.fullmatch(record.code):
        raise ValueError("Geçersiz poz kodu")

    if len(record.description.strip()) < 3:
        raise ValueError("Eksik poz açıklaması")

    if not record.unit.strip():
        raise ValueError("Ölçü birimi eksik")

    if not record.price.is_finite() or record.price <= 0:
        raise ValueError("Geçersiz fiyat")

    if record.source_page < 1:
        raise ValueError("Geçersiz kaynak sayfası")

    if record.record_type not in {"rayic", "imalat"}:
        raise ValueError("Geçersiz kayıt türü")

    if not re.fullmatch(
        r"[a-fA-F0-9]{64}", record.source_sha256
    ):
        raise ValueError("Geçersiz kaynak SHA-256")


@dataclass(frozen=True)
class ParsedRow:
    code: str
    description: str
    unit: str
    price: Decimal
    source_page: int


def parse_position_words(words, source_page: int):
    """Test edilen dÃ¶rt sÃ¼tunlu PDF dÃ¼zeninden adaylarÄ± ayrÄ±ÅŸtÄ±r."""
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

        code = " ".join(t for x, t in items if 43 <= x < 105)
        description = " ".join(t for x, t in items if 105 <= x < 475)
        unit = " ".join(t for x, t in items if 475 <= x < 515)
        raw_price = " ".join(t for x, t in items if 515 <= x <= 565)

        if not code:
            continue

        try:
            if not POSITION_CODE.fullmatch(code):
                raise ValueError("GeÃ§ersiz poz kodu")
            if len(description.strip()) < 3:
                raise ValueError("Eksik aÃ§Ä±klama")
            if not unit:
                raise ValueError("Eksik birim")

            price = parse_turkish_price(raw_price)

            records.append(ParsedRow(
                code, description, unit, price, source_page
            ))
        except ValueError as exc:
            rejected.append({
                "row_y": y,
                "code": code,
                "reason": str(exc),
            })

    return records, rejected

def parse_position_table(page, table, source_page: int):
    """M6.0-A.18: Satır ve hücre geometrisine dayalı pilot ayrıştırıcı.

    Yalnızca doğrulanmış dört sütunlu rayiç tablo düzeni.
    Veritabanına yazmaz. Belirsiz durumlarda hata verir.
    """
    if table.col_count != 4:
        raise ValueError("Beklenmeyen tablo sütun sayısı")

    words = page.get_text("words", sort=True)
    code_pattern = re.compile(r"10\.100\.\d{4}")

    def cell_text(cell):
        if cell is None:
            return ""

        x0, y0, x1, y1 = cell
        selected = []

        for w in words:
            cx = (w[0] + w[2]) / 2
            cy = (w[1] + w[3]) / 2

            if x0 <= cx < x1 and y0 <= cy < y1:
                selected.append(w)

        selected.sort(key=lambda w: (round(w[1], 1), w[0]))
        return " ".join(w[4] for w in selected).strip()

    records = []
    rejected = []
    seen = set()

    for row_number, row in enumerate(table.rows, 1):
        cells = row.cells

        if len(cells) != 4:
            rejected.append({
                "row": row_number,
                "reason": "Beklenmeyen hücre sayısı"
            })
            continue

        values = [cell_text(c) for c in cells]
        code, description, unit, raw_price = values

        # Başlık ve bölüm ayırıcılarını veri sayma.
        if not code_pattern.fullmatch(code):
            # Pilot düzeninde 10.100 ile başlayan
            # bozuk bir kodu sessizce geçme.
            if "10.100" in code:
                rejected.append({
                    "row": row_number,
                    "code": code,
                    "reason": "Bozuk poz kimliği"
                })
            continue

        try:
            if code in seen:
                raise ValueError("Tekrarlanan poz kodu")

            if len(description) < 3:
                raise ValueError("Eksik açıklama")

            if not unit:
                raise ValueError("Eksik ölçü birimi")

            price = parse_turkish_price(raw_price)

            seen.add(code)

            records.append(ParsedRow(
                code=code,
                description=description,
                unit=unit,
                price=price,
                source_page=source_page
            ))

        except ValueError as exc:
            rejected.append({
                "row": row_number,
                "code": code,
                "reason": str(exc)
            })

    # Geometriden bağımsız poz kodu kapsam kontrolü.
    source_codes = [
        w[4] for w in words
        if code_pattern.fullmatch(w[4])
    ]

    from collections import Counter

    counts = Counter(source_codes)
    parsed_codes = {r.code for r in records}

    for code, count in counts.items():
        if count != 1:
            rejected.append({
                "code": code,
                "reason": "Kaynakta mükerrer poz kodu"
            })
        if code not in parsed_codes:
            rejected.append({
                "code": code,
                "reason": "Kaynak poz ayrıştırılamadı"
            })

    return records, rejected

