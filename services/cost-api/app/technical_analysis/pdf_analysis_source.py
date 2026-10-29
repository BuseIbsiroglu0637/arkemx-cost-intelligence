"""Read-only PDF source pilot for position 15.275.1111.

Validates one known document and one known analysis layout.
Does not approve candidates or write to a database.
"""

import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf

POSITION = "15.275.1111"
PDF_PAGE = 423
PRINTED_PAGE = 418

EXPECTED_SHA256 = (
    "81c814c4673af09bd295d1bc0a151ef2a1"
    "eee3a4f9ddc66754bf1410bb6ce1fa"
)

EXPECTED_CODES = (
    "19.100.2504",
    "19.100.2508",
    "10.130.9991",
    "10.100.1012",
    "10.100.1044",
    "10.100.1062",
    "10.100.1062",
)

CENT = Decimal("0.01")

ROW_PATTERN = re.compile(
    r"^[ \t]*(?P<code>(?:10|19)\.\d{3}\.\d{4})[ \t]*\r?\n"
    r"(?P<description>"
    r"(?:(?!^[ \t]*\d{2}\.\d{3}\.\d{4}[ \t]*\r?$).)+?"
    r")"
    r"^[ \t]*(?P<unit>m³|Sa)[ \t]*\r?\n"
    r"[ \t]*(?P<quantity>\d+(?:,\d+)?)[ \t]*\r?\n"
    r"[ \t]*(?P<price>[\d.]+,\d{2})[ \t]*\r?\n"
    r"[ \t]*(?P<amount>[\d.]+,\d{2})[ \t]*(?=\r?$)",
    re.MULTILINE | re.DOTALL,
)

TOTAL_PATTERN = re.compile(
    r"Malzeme \+ İşçilik Tutarı\s+"
    r"25 % Yüklenici kârı ve genel giderler\s+"
    r"1 m² Fiyatı\s+"
    r"([\d.]+,\d{2})\s+"
    r"([\d.]+,\d{2})\s+"
    r"([\d.]+,\d{2})"
)


def number(value: str) -> Decimal:
    """Parse the Turkish numeric format used in this document."""
    return Decimal(value.replace(".", "").replace(",", "."))


def rounded(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def evidence(text: str, start: int, end: int) -> dict:
    """Offsets refer to the unmodified extracted page text."""
    return {
        "quote": text[start:end],
        "start": start,
        "end": end,
        "offset_basis": "extracted_page_text",
        "pdf_page": PDF_PAGE,
    }


def parse_analysis_text(page_text: str) -> dict:
    """Parse only the supported position from its original page text."""
    header = re.compile(
        r"^Poz No[ \t]*\r?\n"
        r"(?P<code>15\.\d{3}\.\d{4})[ \t]*$",
        re.MULTILINE,
    )
    headers = list(header.finditer(page_text))
    targets = [
        index
        for index, item in enumerate(headers)
        if item.group("code") == POSITION
    ]

    if len(targets) != 1:
        raise ValueError("Expected exactly one target position header")

    index = targets[0]

    if index + 1 >= len(headers):
        raise ValueError("Next position boundary could not be verified")

    next_header = headers[index + 1]
    if next_header.group("code") != "15.275.1112":
        raise ValueError("Unexpected next position in pilot layout")

    start = headers[index].start()
    section = page_text[start:next_header.start()]

    if not re.search(r"^m²[ \t]*$", section, re.MULTILINE):
        raise ValueError("Expected square-metre analysis unit")

    if not re.search(r"^-418-[ \t]*$", page_text, re.MULTILINE):
        raise ValueError("Unexpected printed page number")

    description_match = re.search(
        r"^1 m³ dişli kuma\b.*?(?=^Ölçü:)",
        section,
        re.MULTILINE | re.DOTALL,
    )
    if description_match is None:
        raise ValueError("Technical description could not be isolated")

    resources = []
    resource_area = section[:description_match.start()]

    for match in ROW_PATTERN.finditer(resource_area):
        quantity = number(match.group("quantity"))
        price = number(match.group("price"))
        amount = number(match.group("amount"))

        if rounded(quantity * price) != amount:
            raise ValueError(
                f"Resource arithmetic mismatch: {match.group('code')}"
            )

        resources.append({
            "code": match.group("code"),
            "description": match.group("description").strip(),
            "unit": match.group("unit"),
            "quantity": str(quantity),
            "unit_price": str(price),
            "amount": str(amount),
            "evidence": evidence(
                page_text,
                start + match.start(),
                start + match.end(),
            ),
        })

    codes = tuple(item["code"] for item in resources)
    if codes != EXPECTED_CODES:
        raise ValueError("Missing, extra or unexpected resource rows")

    totals = list(TOTAL_PATTERN.finditer(section))
    if len(totals) != 1:
        raise ValueError("Expected exactly one analysis total block")

    total_match = totals[0]
    subtotal, overhead, total = (
        number(total_match.group(group))
        for group in (1, 2, 3)
    )

    resource_sum = sum(
        (Decimal(item["amount"]) for item in resources),
        Decimal("0"),
    )

    if resource_sum != subtotal:
        raise ValueError("Resource sum differs from stated subtotal")

    if rounded(subtotal * Decimal("0.25")) != overhead:
        raise ValueError("Overhead differs from stated 25 percent")

    if subtotal + overhead != total:
        raise ValueError("Final analysis total is inconsistent")

    return {
        "schema": "arkemx.pdf_analysis_source.v1",
        "position_code": POSITION,
        "unit": "m²",
        "read_only": True,
        "approval_allowed": False,
        "resources": resources,
        "technical_description": evidence(
            page_text,
            start + description_match.start(),
            start + description_match.end(),
        ),
        "totals": {
            "material_and_labor": str(subtotal),
            "overhead_rate": "0.25",
            "overhead_and_profit": str(overhead),
            "total": str(total),
            "currency": "TRY",
            "evidence": evidence(
                page_text,
                start + total_match.start(),
                start + total_match.end(),
            ),
        },
    }


def read_analysis(path: str | Path) -> dict:
    """Read and verify the pinned pilot PDF without changing it."""
    source = Path(path)

    with source.open("rb") as stream:
        pdf_bytes = stream.read()

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Source PDF SHA-256 does not match pilot document")

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        page_count = len(document)

        if page_count != 704:
            raise ValueError("Unexpected pilot PDF page count")

        page_text = document[PDF_PAGE - 1].get_text(
            "text", sort=False
        )

    result = parse_analysis_text(page_text)
    result["source"] = {
        "filename": source.name,
        "sha256": digest,
        "pdf_page": PDF_PAGE,
        "printed_page": PRINTED_PAGE,
        "page_count": page_count,
        "price_date": "2026-01-01",
        "page_text": page_text,
    }
    return result