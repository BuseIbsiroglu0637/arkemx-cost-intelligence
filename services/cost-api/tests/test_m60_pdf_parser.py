
"""M6.0-A: PDF katalog veri doğrulama testleri."""

from decimal import Decimal

import pytest

from app.pdf_catalog_parser import (
    CatalogRecord,
    parse_turkish_price,
    validate_record,
)


def test_turkish_prices():
    assert parse_turkish_price("1.250,00") == Decimal("1250.00")
    assert parse_turkish_price("310,00") == Decimal("310.00")
    assert parse_turkish_price("1.000.000,00") == Decimal("1000000.00")


@pytest.mark.parametrize("value", [
    "1,250.00",
    "1250.00",
    "-1250,00",
    "1.25,00",
    "abc",
    "",
])
def test_invalid_prices(value):
    with pytest.raises(ValueError):
        parse_turkish_price(value)


def test_valid_catalog_record():
    record = CatalogRecord(
        code="10.100.1001",
        description="Sentetik işçilik test kaydı",
        unit="Sa",
        price=Decimal("310.00"),
        source_page=8,
        record_type="rayic",
        source_sha256="a" * 64,
    )

    validate_record(record)


def test_invalid_record_type():
    record = CatalogRecord(
        code="TEST.001",
        description="Sentetik test kaydı",
        unit="m3",
        price=Decimal("1250.00"),
        source_page=1,
        record_type="bilinmeyen",
        source_sha256="a" * 64,
    )

    with pytest.raises(ValueError):
        validate_record(record)
