
"""M6.0-A.34 - Fail-closed PDF evidence safety tests."""

from types import SimpleNamespace

import pytest

from app.pdf_catalog_parser import parse_position_table
from app.pdf_catalog_trace import position_full_bbox
from test_m621_multiline_safety import create_test_page


def make_word(x, y, value):
    return (x, y, x + 10, y + 8, value)


def make_row(y0, y1):
    return SimpleNamespace(
        cells=[
            (0, y0, 110, y1),
            (110, y0, 470, y1),
            (470, y0, 520, y1),
            (520, y0, 610, y1),
        ],
        bbox=(0, y0, 610, y1),
    )


def make_fake_page(words):
    return SimpleNamespace(
        get_text=lambda *args, **kwargs: words
    )


def test_two_codes_in_same_cell_rejected():
    """Two position codes in one cell must not be accepted."""
    words = [
        make_word(5, 5, "10.100.1001"),
        make_word(50, 5, "10.100.1002"),
        make_word(120, 5, "Sentetik"),
        make_word(480, 5, "Sa"),
        make_word(540, 5, "310,00"),
    ]

    page = make_fake_page(words)
    table = SimpleNamespace(
        col_count=4,
        rows=[make_row(0, 30)],
    )

    records, rejected = parse_position_table(page, table, 1)

    assert not records
    assert rejected
    assert any(
        "poz kimligi" in item.get("reason", "").lower()
        for item in rejected
    ), rejected


def test_ambiguous_continuation_rejected():
    """Continuation rows containing a unit are ambiguous."""
    words = [
        make_word(5, 5, "10.100.1001"),
        make_word(120, 5, "Sentetik"),
        make_word(480, 5, "Sa"),
        make_word(540, 5, "310,00"),
        make_word(120, 25, "Devam"),
        make_word(480, 25, "Sa"),
    ]

    page = make_fake_page(words)
    table = SimpleNamespace(
        col_count=4,
        rows=[
            make_row(0, 20),
            make_row(20, 40),
        ],
    )

    records, rejected = parse_position_table(page, table, 1)

    # A candidate may be parsed, but the page must be
    # flagged for review when an ambiguous row exists.
    assert rejected
    assert any(
        item.get("reason") == "Belirsiz devam satiri"
        for item in rejected
    ), rejected


def test_source_description_mismatch_rejected():
    """Evidence cannot approve a shortened source description."""
    doc, page = create_test_page(second_code=True)

    try:
        table = page.find_tables(
            strategy="lines_strict"
        ).tables[0]

        code_word = next(
            word for word in page.get_text("words")
            if word[4] == "10.100.1001"
        )

        with pytest.raises(
            ValueError,
            match="Kaynak aciklama",
        ):
            position_full_bbox(
                page,
                table,
                code_word,
                "Sentetik beton uygulamasi",
            )
    finally:
        doc.close()
