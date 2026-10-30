
"""M6.0-A.26: Çok satırlı PDF poz tarifi güvenlik testleri."""

import pymupdf

from app.pdf_catalog_parser import parse_position_table


def create_test_page(second_code=False, continuation_row=False):
    """Dört sütunlu, iki satırlı sentetik PDF tablosu oluşturur."""

    doc = pymupdf.open()
    page = doc.new_page(width=640, height=842)

    # Tablo sütun ve satır sınırları
    left, right = 40, 610
    top, bottom = 100, 220 if continuation_row else 180

    # Dört sütunun dikey çizgileri
    for x in (40, 105, 470, 510, 610):
        page.draw_line(
            (x, top),
            (x, bottom),
            color=(0, 0, 0),
            width=0.8,
        )

    # İki fiziksel satırın yatay çizgileri
    for y in ((100, 140, 180, 220) if continuation_row else (100, 140, 180)):
        page.draw_line(
            (left, y),
            (right, y),
            color=(0, 0, 0),
            width=0.8,
        )

    # İlk poz: iki satıra yayılan açıklama
    page.insert_text((45, 115), "10.100.1001", fontsize=8)
    page.insert_text(
        (110, 115),
        "Sentetik beton uygulamasi",
        fontsize=8,
    )
    page.insert_text(
        (110, 155 if continuation_row else 130),
        "nakliye ve iscilik dahil",
        fontsize=8,
    )
    page.insert_text((480, 115), "m3", fontsize=8)
    page.insert_text((525, 115), "1250,00", fontsize=8)

    # İsteğe bağlı ikinci poz
    if second_code:
        second_y = 195 if continuation_row else 155
        page.insert_text((45, second_y), "10.100.1002", fontsize=8)
        page.insert_text(
            (110, second_y),
            "Ikinci sentetik imalat",
            fontsize=8,
        )
        page.insert_text((480, second_y), "m3", fontsize=8)
        page.insert_text((525, second_y), "2500,00", fontsize=8)

    return doc, page


def test_multiline_description_preserved():
    """İki satırlı açıklamanın tek pozda korunmasını doğrular."""

    doc, page = create_test_page()

    try:
        # Metinden kaynaklanan yapay tablo sınırlarını azalt
        tables = page.find_tables(strategy="lines_strict")

        assert len(tables.tables) == 1, (
            f"Beklenen 1 tablo, bulunan: {len(tables.tables)}"
        )

        table = tables.tables[0]

        assert table.col_count == 4, (
            f"Beklenen 4 sütun, bulunan: {table.col_count}"
        )

        records, rejected = parse_position_table(
            page,
            table,
            1,
        )

        assert len(records) == 1, (records, rejected)
        assert not rejected, rejected

        record = records[0]

        assert record.code == "10.100.1001"

        assert record.description == (
            "Sentetik beton uygulamasi "
            "nakliye ve iscilik dahil"
        )

        assert record.unit == "m3"
        assert record.price == 1250

    finally:
        doc.close()


def test_second_position_is_not_merged():
    """İkinci pozun ilk pozla birleşmediğini doğrular."""

    doc, page = create_test_page(second_code=True)

    try:
        tables = page.find_tables(strategy="lines_strict")

        assert len(tables.tables) == 1, (
            f"Beklenen 1 tablo, bulunan: {len(tables.tables)}"
        )

        table = tables.tables[0]

        assert table.col_count == 4, (
            f"Beklenen 4 sütun, bulunan: {table.col_count}"
        )

        records, rejected = parse_position_table(
            page,
            table,
            1,
        )

        assert len(records) == 2, (records, rejected)
        assert not rejected, rejected

        assert [r.code for r in records] == [
            "10.100.1001",
            "10.100.1002",
        ]

        assert [r.price for r in records] == [
            1250,
            2500,
        ]

        assert records[0].description == (
            "Sentetik beton uygulamasi "
            "nakliye ve iscilik dahil"
        )

        assert records[1].description == (
            "Ikinci sentetik imalat"
        )

        assert "Ikinci" not in records[0].description
        assert "nakliye" not in records[1].description

    finally:
        doc.close()
