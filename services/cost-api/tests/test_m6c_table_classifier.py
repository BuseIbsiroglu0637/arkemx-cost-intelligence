
"""M6.0-C.3 - PDF table classification regression tests."""

import os
from pathlib import Path

import pymupdf
import pytest

from app.pdf_table_classifier import (
    classify_table,
    find_table_overlaps,
)


class FakeTable:
    def __init__(self, columns, rows):
        self.col_count = columns
        self.rows = rows

    def extract(self):
        return self.rows


HEADER_4 = [
    "a PozNo", "tanm", "olcubirimi", "rayicfiyattl"
]

HEADER_5 = [
    "a PozNo", "tanm", "olcubirimi",
    "satnalmayeri", "rayicfiyattl"
]


def test_four_column_rayic():
    table = FakeTable(4, [
        HEADER_4,
        ["101001001 . .", "Tasci ustasi", "Sa", "31000 ,"],
    ])

    result = classify_table(table)

    assert result.family == "RAYIC_4_SUTUN_ADAYI"
    assert result.codes == ("10.100.1001",)


def test_five_column_rayic():
    table = FakeTable(5, [
        HEADER_5,
        [
            "103101301 . .", "EPS TR100",
            "m3", "Isbasinda", "165000 ,"
        ],
    ])

    result = classify_table(table)

    assert result.family == "RAYIC_5_SUTUN_ADAYI"
    assert result.codes == ("10.310.1301",)


def test_technical_table_is_not_rayic():
    table = FakeTable(3, [
        ["SIRA NO", "TS NO", "STANDARDIN ADI"],
        ["1", "TS ISO 8528", "Teknik standart"],
    ])

    result = classify_table(table)

    assert result.family == "TEKNIK_VEYA_POZSUZ_TABLO"
    assert not result.codes


def test_malformed_identity_requires_review():
    table = FakeTable(5, [
        HEADER_5,
        [
            "10.310.X301", "EPS TR100",
            "m3", "Isbasinda", "165000 ,"
        ],
    ])

    result = classify_table(table)

    assert result.family == "BELIRSIZ_INCELE"
    assert result.malformed_codes


def test_duplicate_identity_requires_review():
    table = FakeTable(4, [
        HEADER_4,
        ["101001001 . .", "Birinci", "Sa", "31000 ,"],
        ["101001001 . .", "Ikinci", "Sa", "32000 ,"],
    ])

    result = classify_table(table)

    assert result.family == "BELIRSIZ_INCELE"
    assert result.duplicate_codes == ("10.100.1001",)


def test_real_pdf_sample():
    source = os.getenv("ARKEMX_PDF")

    if not source or not Path(source).is_file():
        pytest.skip("Local pilot PDF not configured")

    expected = {
        8: ["RAYIC_4_SUTUN_ADAYI"],
        20: ["RAYIC_5_SUTUN_ADAYI"],
        100: ["RAYIC_5_SUTUN_ADAYI"],
        183: ["RAYIC_4_SUTUN_ADAYI"],
        149: [
            "RAYIC_5_SUTUN_ADAYI",
            "KARMASIK_POZ_TABLOSU_INCELE",
        ],
        249: ["TEKNIK_VEYA_POZSUZ_TABLO"] * 2,
        483: ["TEKNIK_VEYA_POZSUZ_TABLO"],
        485: ["TEKNIK_VEYA_POZSUZ_TABLO"],
    }

    with pymupdf.open(source) as doc:
        for number, expected_families in expected.items():
            tables = doc[number - 1].find_tables().tables
            profiles = [
                classify_table(table)
                for table in tables
            ]

            assert [
                profile.family for profile in profiles
            ] == expected_families, number

            if number == 149:
                overlaps = find_table_overlaps(profiles)

                assert len(overlaps) == 1
                assert len(overlaps[0][2]) == 9

# M6.0-D.3 - New catalog family tests


def test_three_column_rayic_family():
    table = FakeTable(3, [
        ["a PozNo", "Tanımı", "RayiçFiyatı TL"],
        ["101101001 . .", "Taşıt", "73500 ,"],
    ])

    result = classify_table(table)

    assert result.family == "RAYIC_3_SUTUN_ADAYI"
    assert result.codes == ("10.110.1001",)


def test_four_column_installation_family():
    table = FakeTable(4, [
        [
            "a PozNo",
            "Yapılacakİ şinCinsi",
            "Montajlı BirimFiyat TL",
            "MontajBedeli (TL)",
        ],
        [
            "251001001 . .",
            "25x40cm vidalı",
            "116000 . ,",
            "38875 ,",
        ],
    ])

    result = classify_table(table)

    assert result.family == "MONTAJ_4_SUTUN_ADAYI"
    assert result.codes == ("25.100.1001",)


@pytest.mark.parametrize(
    "page_number, expected_family",
    [
        (11, "RAYIC_3_SUTUN_ADAYI"),
        (12, "RAYIC_3_SUTUN_ADAYI"),
        (251, "MONTAJ_4_SUTUN_ADAYI"),
        (500, "MONTAJ_4_SUTUN_ADAYI"),
        (740, "MONTAJ_4_SUTUN_ADAYI"),
    ],
)
def test_real_pdf_additional_families(
    page_number,
    expected_family,
):
    source = os.getenv("ARKEMX_PDF")

    if not source or not Path(source).is_file():
        pytest.skip("Local pilot PDF not configured")

    with pymupdf.open(source) as doc:
        tables = doc[page_number - 1].find_tables().tables

        assert len(tables) == 1

        profile = classify_table(tables[0])

        assert profile.family == expected_family
        assert profile.codes
        assert not profile.duplicate_codes

def test_real_pdf_page_684_description_only():
    """An explanatory continuation must not become a price record."""

    source = os.getenv("ARKEMX_PDF")

    if not source or not Path(source).is_file():
        pytest.skip("Local pilot PDF not configured")

    with pymupdf.open(source) as doc:
        profiles = []
        tables = []

        for page_number in (683, 684, 685):
            found = doc[page_number - 1].find_tables().tables

            assert len(found) == 1

            tables.append(found[0])
            profiles.append(classify_table(found[0]))

        before, continuation, after = profiles

        assert before.family == "MONTAJ_4_SUTUN_ADAYI"
        assert before.codes

        assert continuation.family == "BELIRSIZ_INCELE"
        assert continuation.codes == ()
        assert continuation.malformed_codes == ()

        rows = tables[1].extract()

        assert len(rows) == 2
        assert not str(rows[1][0] or "").strip()

        # No installed unit price or installation cost.
        assert all(
            not str(rows[1][column] or "").strip()
            for column in (2, 3)
        )

        assert after.family == "MONTAJ_4_SUTUN_ADAYI"
        assert after.codes
