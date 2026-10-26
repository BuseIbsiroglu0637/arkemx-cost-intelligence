
"""M6.0-A.20: Sentetik PDF ayrıştırma güvenlik testleri."""

import pymupdf

from app.pdf_catalog_parser import (
    parse_position_words,
    parse_position_table,
)


def word(x, y, value):
    return (x, y, x + 20, y + 8, value)


def test_complete_synthetic_row():
    """Eksiksiz bir satır doğru ayrıştırılmalı."""
    words = [
        word(45, 125, "TEST.0001"),
        word(110, 125, "Sentetik"),
        word(160, 125, "imalat"),
        word(490, 125, "m3"),
        word(540, 125, "1.250,00"),
    ]

    records, rejected = parse_position_words(words, 8)

    assert len(records) == 1
    assert len(rejected) == 0
    assert records[0].code == "TEST.0001"
    assert records[0].price == 1250


def test_missing_price_must_be_rejected():
    """Fiyatı eksik poz kabul edilmemeli."""
    words = [
        word(45, 125, "TEST.0002"),
        word(110, 125, "Sentetik"),
        word(160, 125, "imalat"),
        word(490, 125, "m3"),
    ]

    records, rejected = parse_position_words(words, 8)

    assert len(records) == 0
    assert len(rejected) == 1
    assert rejected[0]["code"] == "TEST.0002"


def test_neighbor_price_must_not_be_reused():
    """Bir pozun fiyatı komşu poz için kullanılmamalı."""
    words = [
        word(45, 125, "TEST.0003"),
        word(110, 125, "Birinci"),
        word(490, 125, "m3"),

        word(45, 140, "TEST.0004"),
        word(110, 140, "Ikinci"),
        word(490, 140, "m3"),
        word(540, 140, "2.500,00"),
    ]

    records, rejected = parse_position_words(words, 8)

    assert len(records) == 1
    assert records[0].code == "TEST.0004"
    assert records[0].price == 2500

    assert len(rejected) == 1
    assert rejected[0]["code"] == "TEST.0003"


def test_shifted_price_must_not_be_accepted():
    """Yanlış fiziksel satırdaki fiyat ilgili poza bağlanmamalı."""
    doc = pymupdf.open()

    try:
        page = doc.new_page(width=595, height=842)

        # Sentetik PDF tablosunun sütun çizgileri
        for x in (40, 105, 475, 515, 565):
            page.draw_line((x, 100), (x, 160))

        # İki ayrı fiziksel satır
        for y in (100, 130, 160):
            page.draw_line((40, y), (565, y))

        # İlk satır: fiyatı eksik poz
        page.insert_text((45, 115), "10.100.1001")
        page.insert_text((110, 115), "Sentetik imalat")
        page.insert_text((485, 115), "m3")

        # Fiyat kasıtlı olarak ikinci satırda
        page.insert_text((530, 145), "1250,00")

        tables = page.find_tables()

        assert len(tables.tables) == 1

        records, rejected = parse_position_table(
            page,
            tables.tables[0],
            1,
        )

        # Yanlış fiyatla kayıt oluşturulmamalı
        assert len(records) == 0

        # Ret gerekçesi doğru pozla ve fiyatla ilgili olmalı
        assert any(
            item.get("code") == "10.100.1001"
            and "fiyat" in item.get("reason", "").lower()
            for item in rejected
        ), rejected

    finally:
        doc.close()
