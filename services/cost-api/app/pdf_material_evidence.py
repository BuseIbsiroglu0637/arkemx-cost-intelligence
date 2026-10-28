
"""M6.0-B.9 - Verifiable material PDF source evidence.

Five-column material tables:
code, description, unit, purchase place, price.

Read-only. Fails closed on ambiguous source evidence.
"""

from collections import Counter
from pathlib import Path

import pymupdf

from app.pdf_catalog_evidence import (
    PositionEvidence,
    sha256_file,
)
from app.pdf_catalog_parser import parse_turkish_price
from app.pdf_material_parser import (
    SOURCE_CODE,
    MaterialParsedRow,
    parse_material_table,
)


def _inside(word, bbox) -> bool:
    x = (word[0] + word[2]) / 2
    y = (word[1] + word[3]) / 2

    return (
        bbox[0] <= x < bbox[2]
        and bbox[1] <= y < bbox[3]
    )


def _cell_text(words, cell) -> str:
    if cell is None:
        return ""

    selected = [
        word for word in words
        if _inside(word, cell)
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


def _row_values(words, row) -> list[str]:
    if len(row.cells) != 5:
        raise ValueError("Beklenmeyen hucre sayisi")

    return [
        _cell_text(words, cell)
        for cell in row.cells
    ]


def material_full_bbox(
    page,
    table,
    record: MaterialParsedRow,
) -> tuple[float, float, float, float]:
    """Verify fields and calculate complete source geometry."""

    words = page.get_text("words", sort=True)

    matches = [
        index
        for index, row in enumerate(table.rows)
        if _row_values(words, row)[0] == record.code
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Poz baslangic satiri belirsiz: {record.code}"
        )

    start = matches[0]
    first_row = table.rows[start]

    code, description, unit, place, raw_price = (
        _row_values(words, first_row)
    )

    if code != record.code:
        raise ValueError("Kaynak poz kodu uyusmuyor")

    if not unit or unit != record.unit:
        raise ValueError("Kaynak birimi uyusmuyor")

    if not place or place != record.purchase_place:
        raise ValueError("Satin alma yeri uyusmuyor")

    if not raw_price:
        raise ValueError("Kaynak fiyati eksik")

    price = parse_turkish_price(raw_price)

    if price != record.price:
        raise ValueError("Kaynak fiyati uyusmuyor")

    included_rows = [first_row]
    description_parts = [description]

    # Include description-only continuation rows.
    # Never include the next position or ambiguous data.
    for index in range(start + 1, len(table.rows)):
        row = table.rows[index]

        next_code, desc, next_unit, next_place, next_price = (
            _row_values(words, row)
        )

        if (
            not next_code
            and desc
            and not next_unit
            and not next_place
            and not next_price
        ):
            included_rows.append(row)
            description_parts.append(desc)
            continue

        break

    source_description = " ".join(
        " ".join(description_parts).split()
    )

    parsed_description = " ".join(
        record.description.split()
    )

    if source_description != parsed_description:
        raise ValueError(
            "Kaynak malzeme aciklamasi uyusmuyor"
        )

    bbox = (
        float(min(row.bbox[0] for row in included_rows)),
        float(min(row.bbox[1] for row in included_rows)),
        float(max(row.bbox[2] for row in included_rows)),
        float(max(row.bbox[3] for row in included_rows)),
    )

    if not page.rect.contains(pymupdf.Rect(bbox)):
        raise ValueError("Kaynak koordinati sayfa disinda")

    return bbox


def link_material_evidence(
    page,
    table,
    *,
    source_pdf_path,
    source_page: int,
    catalog_year: int,
    catalog_period: str,
) -> list[tuple[MaterialParsedRow, PositionEvidence]]:
    """Link every material position to verified PDF evidence."""

    source_path = Path(source_pdf_path).resolve()

    if not source_path.is_file():
        raise ValueError("Kaynak PDF bulunamadi")

    document = page.parent

    if document is None or not document.name:
        raise ValueError("PDF kaynak yolu belirlenemedi")

    opened_path = Path(document.name).resolve()

    if source_path != opened_path:
        raise ValueError("Kaynak PDF dosyasi uyusmuyor")

    if source_page != page.number + 1:
        raise ValueError("PDF sayfa numarasi uyusmuyor")

    if table.col_count != 5:
        raise ValueError("Beklenmeyen tablo sutun sayisi")

    records, rejected = parse_material_table(
        page,
        table,
        source_page,
    )

    if rejected or not records:
        raise ValueError(
            f"Malzeme katalog incelemesi gerekli: {rejected}"
        )

    words = page.get_text("words", sort=True)

    source_counts = Counter(
        word[4]
        for word in words
        if _inside(word, table.bbox)
        and SOURCE_CODE.fullmatch(word[4])
    )

    parsed_counts = Counter(
        record.code for record in records
    )

    if (
        source_counts != parsed_counts
        or any(count != 1 for count in source_counts.values())
    ):
        raise ValueError(
            "Kaynak ve ayris­tirilan poz kimlikleri uyusmuyor"
        )

    document_hash = sha256_file(source_path)

    page_size = (
        float(page.rect.width),
        float(page.rect.height),
    )

    results: list[
        tuple[MaterialParsedRow, PositionEvidence]
    ] = []

    for record in records:
        bbox = material_full_bbox(
            page,
            table,
            record,
        )

        evidence = PositionEvidence(
            code=record.code,
            source_page=record.source_page,
            source_bbox=bbox,
            page_size=page_size,
            source_sha256=document_hash,
            catalog_year=catalog_year,
            catalog_period=catalog_period,
            record_type="rayic",
            validation_status="needs_review",
        )

        results.append((record, evidence))

    return results
