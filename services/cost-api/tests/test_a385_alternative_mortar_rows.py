
"""A3.8.5 - Verify alternative mortar resource arithmetic."""

import os
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf

from app.technical_analysis.alternative_mortar_source import (
    read_alternative_mortar,
)

ROWS = (
    ("10.130.1007", "m\u00b3", "1", "431.00", "431.00"),
    ("10.130.1209", "Ton", "0.3", "2550.00", "765.00"),
    ("10.130.9991", "m\u00b3", "0.23", "55.00", "12.65"),
    ("10.100.1062", "Sa", "2.5", "205.00", "512.50"),
    ("10.100.1062", "Sa", "1", "205.00", "205.00"),
)


def parse_number(value):
    return Decimal(value.replace(".", "").replace(",", "."))


def test_alternative_mortar_pdf_resource_arithmetic():
    path = os.environ.get("ARKEMX_ALT_PDF")
    assert path and Path(path).is_file()

    source = read_alternative_mortar(path)

    assert source["read_only"] is True
    assert source["approval_allowed"] is False
    assert source["position_code"] == "19.100.2506"

    with pymupdf.open(path) as document:
        text = document[696].get_text("text")

    start = text.index("19.100.2506")
    end = text.index("19.100.2507")
    assert start < end

    section = text[start:end]

    matches = list(
        re.finditer(
            r"(?m)^10\.\d{3}\.\d{4}[ \t]*$",
            section,
        )
    )

    assert len(matches) == len(ROWS)
    total = Decimal(0)

    for index, (code, unit, qty, price, amount) in enumerate(ROWS):
        end_offset = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(section)
        )

        block = section[matches[index].start():end_offset]
        lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip()
        ]

        assert lines[0] == code

        unit_indexes = [
            i for i, line in enumerate(lines)
            if line == unit
        ]
        assert len(unit_indexes) == 1

        offset = unit_indexes[0]

        quantity = parse_number(lines[offset + 1])
        unit_price = parse_number(lines[offset + 2])
        line_amount = parse_number(lines[offset + 3])

        assert quantity == Decimal(qty)
        assert unit_price == Decimal(price)
        assert line_amount == Decimal(amount)

        calculated = (quantity * unit_price).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        assert calculated == line_amount
        total += line_amount

    assert total == Decimal("1926.15")
    assert total == Decimal(source["unit_price_tl"])
