
"""A3.8.3 - Verified alternative mortar PDF price source.

Reads only position 19.100.2506 from the pinned 2026 PDF.
Does not change the original analysis or write to a database.
"""

import hashlib
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

import pymupdf

EXPECTED_SHA256 = (
    "ca7453f9e8d583e28bb16130b19487"
    "edc8308831017d8d7e4daa0367c8038431"
)

POSITION = "19.100.2506"
NEXT_POSITION = "19.100.2507"
PAGE = 697
EXPECTED_PRICE = Decimal("1926.15")

TITLE = "300 Kg çimento dozlu ince harç yapılması"

PRICE_PATTERN = re.compile(
    r"1[ \t]*m(?:\u00b3|3|\^3)[ \t]*"
    r"Fiyat(?:\u0131|i)[ \t\r\n]*"
    r"(?P<price>[\d.]+,\d{2})",
    re.IGNORECASE,
)


def normalize(value: str) -> str:
    value = value.replace("ı", "i").replace("İ", "I")
    value = unicodedata.normalize("NFKD", value).casefold()

    return "".join(
        char
        for char in value
        if char.isalnum()
        and not unicodedata.combining(char)
    )


def parse_price_page(text: str) -> dict:
    """Verify the price inside the exact position boundaries."""

    if text.count(POSITION) != 1:
        raise ValueError("Alternative position is not unique")

    if text.count(NEXT_POSITION) != 1:
        raise ValueError("Next position boundary is not unique")

    start = text.index(POSITION)
    end = text.index(NEXT_POSITION)

    if end <= start:
        raise ValueError("Invalid position boundaries")

    section = text[start:end]

    if normalize(section).count(normalize(TITLE)) != 1:
        raise ValueError("Alternative position title mismatch")

    matches = list(PRICE_PATTERN.finditer(section))

    if len(matches) != 1:
        raise ValueError("Alternative price is missing or ambiguous")

    match = matches[0]

    price = Decimal(
        match.group("price").replace(".", "").replace(",", ".")
    )

    if price != EXPECTED_PRICE:
        raise ValueError("Unexpected alternative price")

    price_start = start + match.start()
    price_end = start + match.end()

    return {
        "position_code": POSITION,
        "description": TITLE,
        "unit": "m³",
        "unit_price_tl": str(price),
        "evidence": {
            "pdf_page": PAGE,
            "start": price_start,
            "end": price_end,
            "quote": text[price_start:price_end],
            "offset_basis": "extracted_page_text",
        },
    }


def read_alternative_mortar(path: str | Path) -> dict:
    """Read the pinned PDF, verify identity, and extract price."""

    source = Path(path)

    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()

    if digest != EXPECTED_SHA256:
        raise ValueError("Alternative PDF SHA-256 mismatch")

    with pymupdf.open(source) as document:
        if document.page_count != 706:
            raise ValueError("Unexpected PDF page count")

        page_text = document[PAGE - 1].get_text("text")

    result = parse_price_page(page_text)

    result["source"] = {
        "filename": source.name,
        "sha256": digest,
        "pdf_page": PAGE,
        "price_date": "2026-01-01",
    }
    result["read_only"] = True
    result["approval_allowed"] = False

    return result
