
"""M6.0-B.8 - Material PDF parser safety tests.

Tests five-column material catalog parsing using synthetic PDFs.
No production data or database writes.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal

import pymupdf
from pymupdf.table import Table

from app.pdf_material_parser import parse_material_table

MaterialCells = tuple[str, str, str, str, str]

TABLE_HEADER: MaterialCells = (
    "Poz No",
    "Tanimi",
    "Birimi",
    "Satin Alma Yeri",
    "Rayic Fiyati TL",
)


@contextmanager
def synthetic_table(
    rows: Sequence[MaterialCells],
) -> Iterator[tuple[pymupdf.Page, Table]]:
    """Create a stable synthetic five-column PDF table."""

    if not rows:
        raise ValueError("En az bir test satiri gerekli")

    # Single-row tables may not be reliably detected
    # by every supported PyMuPDF version.
    # Add a realistic header for single-row tests.
    physical_rows = list(rows)

    if len(physical_rows) == 1:
        physical_rows.insert(0, TABLE_HEADER)

    doc = pymupdf.open()

    try:
        page = doc.new_page(width=700, height=842)

        # Five columns:
        # Code | Description | Unit | Purchase place | Price
        xs = (40, 120, 450, 495, 570, 665)

        row_height = 40
        top = 100

        ys = [
            top + row_height * i
            for i in range(len(physical_rows) + 1)
        ]

        # Draw vertical borders.
        for x in xs:
            page.draw_line(
                (x, ys[0]),
                (x, ys[-1]),
                color=(0, 0, 0),
                width=0.8,
            )

        # Draw horizontal borders.
        for y in ys:
            page.draw_line(
                (xs[0], y),
                (xs[-1], y),
                color=(0, 0, 0),
                width=0.8,
            )

        # Write cell values.
        for row_index, row in enumerate(physical_rows):
            assert len(row) == 5

            for column_index, value in enumerate(row):
                if not value:
                    continue

                page.insert_text(
                    (
                        xs[column_index] + 5,
                        ys[row_index] + 22,
                    ),
                    value,
                    fontsize=8,
                )

        tables = page.find_tables(
            strategy="lines_strict"
        ).tables

        assert len(tables) == 1, (
            f"Beklenen 1 tablo, bulunan {len(tables)}"
        )

        table = tables[0]

        assert table.col_count == 5, (
            f"Beklenen 5 sutun, bulunan {table.col_count}"
        )

        assert table.row_count == len(physical_rows), (
            table.row_count,
            len(physical_rows),
        )

        yield page, table

    finally:
        doc.close()


def test_valid_material_position() -> None:
    """A complete material position must be preserved."""

    rows: list[MaterialCells] = [
        (
            "10.310.1301",
            "EPS malzeme TR100",
            "m3",
            "Isbasinda",
            "1.650,00",
        ),
    ]

    with synthetic_table(rows) as (page, table):
        records, rejected = parse_material_table(
            page,
            table,
            source_page=100,
        )

        assert len(records) == 1, (records, rejected)
        assert not rejected, rejected

        record = records[0]

        assert record.code == "10.310.1301"
        assert record.description == "EPS malzeme TR100"
        assert record.unit == "m3"
        assert record.purchase_place == "Isbasinda"
        assert record.price == Decimal("1650.00")
        assert record.source_page == 100


def test_missing_price_not_reused() -> None:
    """Missing price must not be borrowed from the next row."""

    rows: list[MaterialCells] = [
        (
            "10.310.1301",
            "Birinci malzeme",
            "m3",
            "Isbasinda",
            "",
        ),
        (
            "10.310.1302",
            "Ikinci malzeme",
            "m3",
            "Isbasinda",
            "2.500,00",
        ),
    ]

    with synthetic_table(rows) as (page, table):
        records, rejected = parse_material_table(
            page,
            table,
            source_page=100,
        )

        assert len(records) == 1, (records, rejected)

        assert records[0].code == "10.310.1302"
        assert records[0].price == Decimal("2500.00")

        assert all(
            record.code != "10.310.1301"
            for record in records
        )

        assert any(
            item["code"] == "10.310.1301"
            and "fiyat" in item["reason"].lower()
            for item in rejected
        ), rejected


def test_invalid_position_code_rejected() -> None:
    """Malformed numeric position codes must be rejected."""

    rows: list[MaterialCells] = [
        (
            "10.310.X301",
            "Gecersiz malzeme",
            "m3",
            "Isbasinda",
            "1.650,00",
        ),
    ]

    with synthetic_table(rows) as (page, table):
        records, rejected = parse_material_table(
            page,
            table,
            source_page=100,
        )

        assert not records, records

        assert any(
            item["code"] == "10.310.X301"
            for item in rejected
        ), rejected


def test_headings_not_treated_as_positions() -> None:
    """Headers and section headings must not become positions."""

    rows: list[MaterialCells] = [
        TABLE_HEADER,
        (
            "EPS Levhalar",
            "",
            "",
            "",
            "",
        ),
        (
            "10.310.1301",
            "EPS malzeme TR100",
            "m3",
            "Isbasinda",
            "1.650,00",
        ),
    ]

    with synthetic_table(rows) as (page, table):
        records, rejected = parse_material_table(
            page,
            table,
            source_page=100,
        )

        assert len(records) == 1, (records, rejected)
        assert not rejected, rejected

        assert records[0].code == "10.310.1301"
        assert records[0].price == Decimal("1650.00")


def test_multiline_description_preserved() -> None:
    """Description continuation must remain with its position."""

    rows: list[MaterialCells] = [
        (
            "10.310.1301",
            "EPS levha TR100",
            "m3",
            "Isbasinda",
            "1.650,00",
        ),
        (
            "",
            "Ek aciklama",
            "",
            "",
            "",
        ),
    ]

    with synthetic_table(rows) as (page, table):
        records, rejected = parse_material_table(
            page,
            table,
            source_page=100,
        )

        assert len(records) == 1, (records, rejected)
        assert not rejected, rejected

        record = records[0]

        assert record.code == "10.310.1301"

        assert record.description == (
            "EPS levha TR100 Ek aciklama"
        )

        assert record.price == Decimal("1650.00")
        assert record.purchase_place == "Isbasinda"
