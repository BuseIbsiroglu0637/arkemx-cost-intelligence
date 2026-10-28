
"""M6.0-B.9 - Material PDF source evidence tests."""

from dataclasses import replace
from decimal import Decimal

import pymupdf
import pytest

import app.pdf_material_evidence as material_evidence
from app.pdf_catalog_evidence import sha256_file
from app.pdf_material_evidence import link_material_evidence
from app.pdf_material_parser import parse_material_table
from test_m6b_material_safety import synthetic_table


ROWS = [
    (
        "10.310.1301",
        "EPS levha TR100",
        "m3",
        "Isbasinda",
        "1.650,00",
    ),
    ("", "Ek aciklama", "", "", ""),
    (
        "10.310.1302",
        "EPS levha TR200",
        "m3",
        "Isbasinda",
        "2.500,00",
    ),
]


def make_source(tmp_path, rows=None):
    path = tmp_path / "material_catalog.pdf"

    with synthetic_table(ROWS if rows is None else rows) as (
        page,
        _table,
    ):
        page.parent.save(str(path))

    return path


def get_table(page):
    tables = page.find_tables(
        strategy="lines_strict"
    ).tables

    assert len(tables) == 1
    return tables[0]


def link(page, table, path, source_page=1):
    return link_material_evidence(
        page,
        table,
        source_pdf_path=path,
        source_page=source_page,
        catalog_year=2026,
        catalog_period="2026-01",
    )


def test_material_evidence_and_multiline_bbox(tmp_path):
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        table = get_table(page)

        results = link(page, table, path)

        assert len(results) == 2

        first, evidence = results[0]
        second, second_evidence = results[1]

        assert first.code == "10.310.1301"
        assert first.price == Decimal("1650.00")
        assert first.purchase_place == "Isbasinda"

        assert second.code == "10.310.1302"

        assert evidence.code == first.code
        assert evidence.source_page == 1
        assert evidence.source_sha256 == sha256_file(path)
        assert evidence.validation_status == "needs_review"

        assert len(table.rows) == 3

        # The first evidence must include its continuation row.
        assert evidence.source_bbox[1] <= table.rows[0].bbox[1]
        assert evidence.source_bbox[3] >= table.rows[1].bbox[3]

        # It must not include the second position.
        assert evidence.source_bbox[3] <= table.rows[2].bbox[1]
        assert (
            second_evidence.source_bbox[1]
            >= table.rows[2].bbox[1]
        )


def test_wrong_source_file_rejected(tmp_path):
    path = make_source(tmp_path)

    other = tmp_path / "other.pdf"
    other.write_bytes(path.read_bytes())

    with pymupdf.open(str(path)) as doc:
        page = doc[0]

        with pytest.raises(ValueError):
            link(page, get_table(page), other)


def test_wrong_source_page_rejected(tmp_path):
    path = make_source(tmp_path)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]

        with pytest.raises(ValueError):
            link(
                page,
                get_table(page),
                path,
                source_page=100,
            )


def test_missing_price_rejected(tmp_path):
    rows = [
        (
            "10.310.1301",
            "EPS levha TR100",
            "m3",
            "Isbasinda",
            "",
        ),
        (
            "10.310.1302",
            "EPS levha TR200",
            "m3",
            "Isbasinda",
            "2.500,00",
        ),
    ]

    path = make_source(tmp_path, rows)

    with pymupdf.open(str(path)) as doc:
        page = doc[0]

        with pytest.raises(ValueError):
            link(page, get_table(page), path)


def test_source_description_mismatch_rejected(
    tmp_path,
    monkeypatch,
):
    path = make_source(tmp_path)

    original_parser = material_evidence.parse_material_table

    def altered_parser(page, table, source_page):
        records, rejected = original_parser(
            page, table, source_page
        )

        records[0] = replace(
            records[0],
            description="Incorrect description",
        )

        return records, rejected

    monkeypatch.setattr(
        material_evidence,
        "parse_material_table",
        altered_parser,
    )

    with pymupdf.open(str(path)) as doc:
        page = doc[0]

        with pytest.raises(ValueError, match="aciklamasi"):
            link(page, get_table(page), path)
