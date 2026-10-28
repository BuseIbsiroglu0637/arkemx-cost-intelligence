
"""ARKEMX M6.0-A.32 - PDF source evidence linking.

Links parsed positions to PDF source geometry.
Includes description-only continuation rows.

No database writes or automatic engineering approvals.
"""

from collections import Counter
from pathlib import Path

from app.pdf_catalog_parser import (
    RAYIC_CODE,
    parse_position_table,
)
from app.pdf_catalog_evidence import (
    create_position_evidence,
    sha256_file,
)


def _cell_text(words, cell):
    """Read words inside one physical PDF cell."""
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


def position_full_bbox(page, table, code_word, description):
    """Calculate full evidence geometry for one position.

    Includes description-only continuation rows.
    Stops before another position, unit or price.
    Validates that source description matches parsed text.
    """
    words = page.get_text("words", sort=True)

    cx = (code_word[0] + code_word[2]) / 2
    cy = (code_word[1] + code_word[3]) / 2

    matching_indices = []

    for index, row in enumerate(table.rows):
        if len(row.cells) != 4:
            continue

        code_cell = row.cells[0]

        if code_cell is None:
            continue

        x0, y0, x1, y1 = code_cell

        if x0 <= cx < x1 and y0 <= cy < y1:
            matching_indices.append(index)

    if len(matching_indices) != 1:
        raise ValueError(
            "Poz baslangic satiri belirsiz"
        )

    start_index = matching_indices[0]
    first_row = table.rows[start_index]

    first_values = [
        _cell_text(words, cell)
        for cell in first_row.cells
    ]

    first_code, first_description, unit, price = first_values

    if first_code != code_word[4]:
        raise ValueError(
            "Poz kodu kaynak hucresiyle uyusmuyor"
        )

    if not unit or not price:
        raise ValueError(
            "Pozun baslangic satirinda birim veya fiyat eksik"
        )

    included_rows = [first_row]
    description_parts = [first_description]

    # Continue only while following physical rows contain
    # description text without code, unit or price.
    for index in range(start_index + 1, len(table.rows)):
        row = table.rows[index]

        if len(row.cells) != 4:
            break

        code, desc, row_unit, row_price = [
            _cell_text(words, cell)
            for cell in row.cells
        ]

        if not code and desc and not row_unit and not row_price:
            included_rows.append(row)
            description_parts.append(desc)
            continue

        # New position, section header, ambiguous or empty row.
        break

    source_description = " ".join(
        " ".join(description_parts).split()
    )

    parsed_description = " ".join(
        description.split()
    )

    if source_description != parsed_description:
        raise ValueError(
            "Kaynak aciklama ve ayrıştırılan aciklama uyusmuyor"
        )

    bbox = (
        float(min(row.bbox[0] for row in included_rows)),
        float(min(row.bbox[1] for row in included_rows)),
        float(max(row.bbox[2] for row in included_rows)),
        float(max(row.bbox[3] for row in included_rows)),
    )

    return bbox


def link_position_evidence(
    page,
    table,
    *,
    source_pdf_path,
    source_page,
    catalog_year,
    catalog_period,
):
    """Link each parsed position with verifiable PDF evidence."""

    source_path = Path(source_pdf_path).resolve()

    if not page.parent.name:
        raise ValueError("PDF kaynak yolu bulunamadi")

    opened_path = Path(page.parent.name).resolve()

    if source_path != opened_path:
        raise ValueError("Kaynak PDF dosyasi uyusmuyor")

    if source_page != page.number + 1:
        raise ValueError("PDF sayfa numarasi uyusmuyor")

    records, rejected = parse_position_table(
        page,
        table,
        source_page,
    )

    if rejected or not records:
        raise ValueError(
            f"Katalog incelemesi gerekli: {rejected}"
        )

    words = page.get_text("words", sort=True)

    tx0, ty0, tx1, ty1 = table.bbox

    anchors = []

    for word in words:
        if not RAYIC_CODE.fullmatch(word[4]):
            continue

        cx = (word[0] + word[2]) / 2
        cy = (word[1] + word[3]) / 2

        if tx0 <= cx < tx1 and ty0 <= cy < ty1:
            anchors.append(word)

    source_counts = Counter(
        word[4] for word in anchors
    )

    parsed_counts = Counter(
        record.code for record in records
    )

    if source_counts != parsed_counts:
        raise ValueError(
            "Kaynak ve ayrıştırılan poz kimlikleri uyusmuyor"
        )

    document_hash = sha256_file(source_path)

    page_size = (
        float(page.rect.width),
        float(page.rect.height),
    )

    results = []

    for record in records:
        matches = [
            word
            for word in anchors
            if word[4] == record.code
        ]

        if len(matches) != 1:
            raise ValueError(
                f"Poz konumu belirsiz: {record.code}"
            )

        # IMPORTANT:
        # Use all description continuation rows,
        # not only the first physical row.
        bbox = position_full_bbox(
            page,
            table,
            matches[0],
            record.description,
        )

        evidence = create_position_evidence(
            record,
            source_bbox=bbox,
            page_size=page_size,
            source_sha256=document_hash,
            catalog_year=catalog_year,
            catalog_period=catalog_period,
            record_type="rayic",
        )

        results.append((record, evidence))

    return results
