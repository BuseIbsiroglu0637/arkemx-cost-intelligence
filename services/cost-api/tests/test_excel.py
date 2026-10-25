from io import BytesIO
from openpyxl import Workbook
import pytest
from app.excel import read_metraj, parse_quantity, ExcelValidationError, MAX_ROWS


def workbook(rows, headers=("İmalat Açıklaması", "Miktar", "Birim")):
    w = Workbook()
    s = w.active
    s.title = "Mimari Metraj"
    s.append(headers)
    for row in rows:
        s.append(row)
    buf = BytesIO()
    w.save(buf)
    return buf.getvalue()


def test_turkish_headers_and_amounts():
    value = read_metraj(workbook([["Porselen seramik", "1.245,50", "m2"],
                                  ["Gazbeton", 245.5, "m³"]]))
    assert value["mapping"] == {"description": "İmalat Açıklaması", "quantity": "Miktar", "unit": "Birim"}
    assert value["items"][0]["quantity"] == "1245.50"
    assert value["items"][0]["unit"] == "m²"
    assert value["items"][1]["unit"] == "m³"


def test_ambiguous_quantities_block_auto_normalization():
    amount, warnings = parse_quantity("1.234")
    assert amount is None and "QUANTITY_AMBIGUOUS" in warnings
    assert parse_quantity("1,234.50")[0] == 1234.5
    assert parse_quantity("1.234,50")[0] == 1234.5


def test_formula_needs_review():
    result = read_metraj(workbook([["Duvar", "=SUM(2,3)", "m2"]]))
    assert result["items"][0]["review_required"]
    assert "FORMULA_NOT_EVALUATED" in result["items"][0]["issues"]
    assert result["items"][0]["quantity"] is None


def test_duplicate_headers_rejected():
    with pytest.raises(ExcelValidationError, match="Duplicate"):
        read_metraj(workbook([["A", "2", "m2"]], headers=("Miktar", "Miktar", "Birim")))


def test_explicit_columns():
    value = read_metraj(workbook([["Beton", 4, "m3"]], headers=("Ürün", "Toplam", "Ölçü")),
                        columns={"description": "Ürün", "quantity": "Toplam", "unit": "Ölçü"})
    assert value["row_count"] == 1


def test_missing_unit_kept_for_review():
    value = read_metraj(workbook([["Duvar", 12, ""]]))
    assert value["review_count"] == 1
    assert "UNIT_MISSING" in value["items"][0]["issues"]


def test_reject_bad_container():
    with pytest.raises(ExcelValidationError):
        read_metraj(b"not-xlsx")


def test_rows_limit():
    data = workbook([["İş", 1, "m2"]] * (MAX_ROWS + 1))
    with pytest.raises(ExcelValidationError, match="Maximum 2000"):
        read_metraj(data)


def test_header_row_can_be_selected():
    content = workbook([["Mimari Metraj Cetveli", None, None],
                        ["Imalat", "Miktar", "Birim"], ["Boya", 35, "m2"]],
                       headers=("Sayfa", "1", "2"))
    value = read_metraj(content, header_row=3)
    assert value["row_count"] == 1
    assert value["items"][0]["source_row"] == 4
    assert value["items"][0]["quantity"] == "35"
