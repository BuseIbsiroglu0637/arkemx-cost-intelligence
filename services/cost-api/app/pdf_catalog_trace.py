
"""M6.0-A.30 - PDF position evidence linking.

Connect parsed positions to physical PDF source rows.
No database writes or automatic approvals.
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


def link_position_evidence(
    page,
    table,
    *,
    source_pdf_path,
    source_page,
    catalog_year,
    catalog_period,
):
    """Link positions to verifiable source row evidence."""

    source_path = Path(source_pdf_path).resolve()
    opened_path = Path(page.parent.name).resolve()

    if source_path != opened_path:
        raise ValueError("Kaynak PDF dosyasi uyusmuyor")

    if source_page != page.number + 1:
        raise ValueError("PDF sayfa numarasi uyusmuyor")

    records, rejected = parse_position_table(
        page, table, source_page
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
            word for word in anchors
            if word[4] == record.code
        ]

        if len(matches) != 1:
            raise ValueError("Belirsiz poz konumu")

        word = matches[0]
        cx = (word[0] + word[2]) / 2
        cy = (word[1] + word[3]) / 2

        matching_rows = [
            row for row in table.rows
            if (
                row.bbox[0] <= cx < row.bbox[2]
                and row.bbox[1] <= cy < row.bbox[3]
            )
        ]

        if len(matching_rows) != 1:
            raise ValueError(
                f"Poz satiri belirsiz: {record.code}"
            )

        # Anchor geometry: physical row containing the code.
        bbox = tuple(
            float(v) for v in matching_rows[0].bbox
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
