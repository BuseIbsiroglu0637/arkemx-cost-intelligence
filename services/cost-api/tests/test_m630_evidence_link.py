
"""M6.0-A.30 - PDF source linking tests."""

import pymupdf
import pytest

from test_m621_multiline_safety import create_test_page

from app.pdf_catalog_trace import link_position_evidence
from app.pdf_catalog_evidence import sha256_file


def make_source(tmp_path):
    doc, _ = create_test_page(second_code=True)

    path = tmp_path / "synthetic_catalog.pdf"
    doc.save(str(path))
    doc.close()

    return path


def test_position_evidence_linked(tmp_path):
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        tables = page.find_tables(strategy="lines_strict")

        assert len(tables.tables) == 1

        results = link_position_evidence(
            page,
            tables.tables[0],
            source_pdf_path=path,
            source_page=1,
            catalog_year=2026,
            catalog_period="2026-01",
        )

        assert len(results) == 2

        codes = [record.code for record, _ in results]

        assert codes == [
            "10.100.1001",
            "10.100.1002",
        ]

        first = results[0][1]
        second = results[1][1]

        assert first.source_sha256 == sha256_file(path)
        assert first.source_page == 1
        assert first.validation_status == "needs_review"

        assert first.source_bbox != second.source_bbox


def test_wrong_source_file_rejected(tmp_path):
    path = make_source(tmp_path)
    other = tmp_path / "other.pdf"
    other.write_bytes(b"not the source")

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = page.find_tables(
            strategy="lines_strict"
        ).tables[0]

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
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = page.find_tables(
            strategy="lines_strict"
        ).tables[0]

        with pytest.raises(ValueError):
            link_position_evidence(
                page,
                table,
                source_pdf_path=path,
                source_page=8,
                catalog_year=2026,
                catalog_period="2026-01",
            )
