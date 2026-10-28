
"""M6.0-A.32 - PDF source evidence and multiline geometry tests.

Tests:
1. Position-to-source evidence linking
2. Wrong source file rejection
3. Wrong source page rejection
4. Multiline description evidence coverage
"""

import pymupdf
import pytest

from test_m621_multiline_safety import create_test_page

from app.pdf_catalog_trace import link_position_evidence
from app.pdf_catalog_evidence import sha256_file


def make_source(tmp_path):
    """Create a synthetic PDF containing two positions."""
    doc, _ = create_test_page(second_code=True)

    path = tmp_path / "synthetic_catalog.pdf"

    try:
        doc.save(str(path))
    finally:
        doc.close()

    return path


def get_test_table(page):
    """Find the expected four-column synthetic table."""
    tables = page.find_tables(strategy="lines_strict")

    assert len(tables.tables) == 1, (
        f"Expected one table, found {len(tables.tables)}"
    )

    table = tables.tables[0]

    assert table.col_count == 4, (
        f"Expected four columns, found {table.col_count}"
    )

    return table


def test_position_evidence_linked(tmp_path):
    """Each position must link to its own PDF source evidence."""
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = get_test_table(page)

        results = link_position_evidence(
            page,
            table,
            source_pdf_path=path,
            source_page=1,
            catalog_year=2026,
            catalog_period="2026-01",
        )

        assert len(results) == 2

        codes = [
            record.code
            for record, evidence in results
        ]

        assert codes == [
            "10.100.1001",
            "10.100.1002",
        ]

        first_record, first_evidence = results[0]
        second_record, second_evidence = results[1]

        # Position and evidence identities must match.
        assert first_record.code == first_evidence.code
        assert second_record.code == second_evidence.code

        # Both must point to the correct source document.
        expected_hash = sha256_file(path)

        assert first_evidence.source_sha256 == expected_hash
        assert second_evidence.source_sha256 == expected_hash

        assert first_evidence.source_page == 1
        assert second_evidence.source_page == 1

        assert first_evidence.catalog_year == 2026
        assert first_evidence.catalog_period == "2026-01"

        # Automatic engineering approval is not permitted.
        assert first_evidence.validation_status == "needs_review"
        assert second_evidence.validation_status == "needs_review"

        # Each position must have its own evidence region.
        assert first_evidence.source_bbox != second_evidence.source_bbox


def test_wrong_source_file_rejected(tmp_path):
    """Evidence must not link to an unrelated source file."""
    path = make_source(tmp_path)

    other = tmp_path / "other.pdf"
    other.write_bytes(b"not the source")

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = get_test_table(page)

        with pytest.raises(ValueError):
            link_position_evidence(
                page,
                table,
                source_pdf_path=other,
                source_page=1,
                catalog_year=2026,
                catalog_period="2026-01",
            )


def test_wrong_source_page_rejected(tmp_path):
    """A mismatched PDF page number must be rejected."""
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = get_test_table(page)

        with pytest.raises(ValueError):
            link_position_evidence(
                page,
                table,
                source_pdf_path=path,
                source_page=8,
                catalog_year=2026,
                catalog_period="2026-01",
            )


def test_multiline_evidence_bbox(tmp_path):
    """Evidence must include continuation rows, but not the next position."""
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = get_test_table(page)

        results = link_position_evidence(
            page,
            table,
            source_pdf_path=path,
            source_page=1,
            catalog_year=2026,
            catalog_period="2026-01",
        )

        assert len(results) == 2
        assert len(table.rows) == 3

        first_record, first_evidence = results[0]
        second_record, second_evidence = results[1]

        assert first_record.code == "10.100.1001"
        assert second_record.code == "10.100.1002"

        row0 = table.rows[0].bbox
        row1 = table.rows[1].bbox
        row2 = table.rows[2].bbox

        first_bbox = first_evidence.source_bbox
        second_bbox = second_evidence.source_bbox

        # First position covers both its physical rows.
        assert first_bbox[1] <= row0[1]
        assert first_bbox[3] >= row1[3]

        # Its evidence must not extend into the next position.
        assert first_bbox[3] <= second_bbox[1]

        # Second position starts in the third physical row.
        assert second_bbox[1] >= row2[1]

        # Each evidence bounding box must be valid.
        for bbox in (first_bbox, second_bbox):
            x0, y0, x1, y1 = bbox

            assert x0 < x1
            assert y0 < y1

            assert 0 <= x0 < page.rect.width
            assert 0 <= x1 <= page.rect.width

            assert 0 <= y0 < page.rect.height
            assert 0 <= y1 <= page.rect.height

        # Description content must remain associated
        # with the correct position.
        assert first_record.description == (
            "Sentetik beton uygulamasi "
            "nakliye ve iscilik dahil"
        )

        assert second_record.description == (
            "Ikinci sentetik imalat"
        )

        # No automatic approval.
        assert first_evidence.validation_status == "needs_review"
        assert second_evidence.validation_status == "needs_review"
