"""A3.48 catalog extraction from PDF table cells; no approval or cost writes."""
import json

import pymupdf
import pytest

from app.a348_official_price_list import ingest_pdf, money, export_local


def source_pdf(*, wrong_date=False):
    doc = pymupdf.open()
    for index in range(10):
        page = doc.new_page(width=595, height=842)
        if index == 5:
            page.insert_text(
                (60, 60), "01.01.2025" if wrong_date else "01.01.2026", fontsize=10,
            )
        if index != 8:
            continue
        for y in (95, 123, 151, 180, 209, 250):
            page.draw_line((44, y), (570, y), width=0.7)
        page.insert_text((45, 110), "15.225.1004", fontsize=8)
        page.insert_text((110, 110), "10 cm gazbeton duvar yapilmasi", fontsize=8)
        page.insert_text((489, 110), "m", fontsize=8)
        page.insert_text((541, 110), "723,73", fontsize=8)
        page.insert_text((45, 137), "25.150.1500", fontsize=8)
        page.insert_text((110, 137), "Depo (Olcu:Ad.)", fontsize=8)
        page.insert_text((45, 165), "25.150.1501", fontsize=8)
        page.insert_text((110, 165), "5000 litre 2500 mm", fontsize=8)
        page.insert_text((460, 165), "64.962,50", fontsize=8)
        page.insert_text((531, 165), "6.587,50", fontsize=8)
    raw = doc.tobytes()
    doc.close()
    # PyMuPDF accepts trailing whitespace; real price source is >15MB.
    return raw + b" " * 100_000


def test_grid_rows_and_pricing_formats_do_not_create_approvals():
    data = ingest_pdf(source_pdf())
    assert data["read_only"] and not data["approval_allowed"] and not data["cost_allowed"]
    assert data["audit"]["codes_seen"] == 3
    assert data["audit"]["records_extracted"] == 3
    assert data["audit"]["unpriced_count"] == 1
    assert data["audit"]["price_cells_extracted"] == 2
    assert data["audit"]["unparsed_count"] == 0
    catalog = {r["code"]: r for r in data["records"]}
    assert catalog["15.225.1004"]["unit"] == "m"
    assert catalog["15.225.1004"]["unit_price"] == "723.73"
    assert catalog["15.225.1004"]["pdf_page"] == 9
    assert catalog["25.150.1500"]["unit_price"] is None
    assert catalog["25.150.1501"]["unit_price"] == "64962.50"
    assert catalog["25.150.1501"]["installation_price"] == "6587.50"
    assert catalog["25.150.1501"]["parent_code"] == "25.150.1500"
    assert catalog["25.150.1501"]["unit"] is None
    assert all(row["cost_allowed"] is False for row in catalog.values())


def test_rejects_wrong_edition_and_non_pdf():
    with pytest.raises(ValueError, match="expected 01.01.2026"):
        ingest_pdf(source_pdf(wrong_date=True))
    with pytest.raises(ValueError, match="Expected a readable"):
        ingest_pdf(b"%PDF-short")


def test_turkish_decimal_and_no_implicit_zero_prices():
    assert money("1.234,56") == "1234.56"
    assert money("0,00") is None
    assert money("BAD") is None


def test_local_private_export_does_not_overwrite_data(tmp_path):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(source_pdf())
    original = pdf.read_bytes()
    index = tmp_path / "private" / "catalog.json"
    audit = export_local(pdf, index)
    assert audit["records_extracted"] == 3
    result = json.loads(index.read_text(encoding="utf-8"))
    assert result["records"][0]["code"] == "15.225.1004"
    with pytest.raises(FileExistsError):
        export_local(pdf, index)
    assert pdf.read_bytes() == original
