"""Pinned auxiliary-analysis reader for three mortar analyses.

Read-only source verification. No engineering approval or cost-draft writes.
"""

import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf

EXPECTED_SHA256 = (
    "ca7453f9e8d583e28bb16130b19487ed"
    "c8308831017d8d7e4daa0367c8038431"
)

# Physical PDF page, printed page, sand resource, cement tonnes per source unit.
SUPPORTED = {
    "19.100.2504": (696, 1392, "10.130.1005", Decimal("0.25")),
    "19.100.2506": (697, 1393, "10.130.1007", Decimal("0.30")),
    "19.100.2508": (698, 1394, "10.130.1007", Decimal("0.35")),
}

HEADER = re.compile(
    r"^Poz No[ \t]*\r?\n(?P<code>19\.\d{3}\.\d{4})[ \t]*$",
    re.MULTILINE,
)

ROW = re.compile(
    r"^[ \t]*(?P<code>10\.\d{3}\.\d{4})[ \t]*\r?\n"
    r"(?P<description>"
    r"(?:(?!^[ \t]*\d{2}\.\d{3}\.\d{4}[ \t]*\r?$).)+?"
    r")"
    r"^[ \t]*(?P<unit>m³|Ton|Sa)[ \t]*\r?\n"
    r"[ \t]*(?P<quantity>\d+(?:,\d+)?)[ \t]*\r?\n"
    r"[ \t]*(?P<price>[\d.]+,\d{2})[ \t]*\r?\n"
    r"[ \t]*(?P<amount>[\d.]+,\d{2})[ \t]*(?=\r?$)",
    re.MULTILINE | re.DOTALL,
)

TOTAL = re.compile(r"1 m³ Fiyatı\s+([\d.]+,\d{2})")


def number(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def evidence(text: str, start: int, end: int, page: int) -> dict:
    return {
        "quote": text[start:end],
        "start": start,
        "end": end,
        "offset_basis": "extracted_page_text",
        "pdf_page": page,
    }


def parse_auxiliary_text(page_text: str, position_code: str) -> dict:
    """Parse one supported analysis, never merging adjacent analyses."""
    if position_code not in SUPPORTED:
        raise ValueError("Unsupported auxiliary position")
    pdf_page, printed_page, sand_code, cement_tonnes = SUPPORTED[position_code]
    headers = list(HEADER.finditer(page_text))
    targets = [i for i, match in enumerate(headers) if match.group("code") == position_code]
    if len(targets) != 1:
        raise ValueError("Expected exactly one auxiliary position header")
    index = targets[0]
    start = headers[index].start()
    end = headers[index + 1].start() if index + 1 < len(headers) else len(page_text)
    section = page_text[start:end]
    if "Yardımcı Analizler" not in page_text:
        raise ValueError("Expected auxiliary analysis page")
    if not re.search(r"(?m)^1\.01\.2026[ \t]*$", page_text):
        raise ValueError("Unexpected source date")
    if not re.search(rf"(?m)^-{printed_page}-[ \t]*$", page_text):
        raise ValueError("Unexpected printed page")
    title = re.search(r"Analizin Adı\s+(.+?)(?=\s+Tanımı)", section, re.DOTALL)
    if title is None:
        raise ValueError("Missing auxiliary title")
    materials = re.search(r"(?m)^Malzeme[ \t]*:?[ \t]*$", section)
    total_matches = list(TOTAL.finditer(section))
    if materials is None or len(total_matches) != 1:
        raise ValueError("Missing or ambiguous resource/total boundary")
    total_match = total_matches[0]
    if materials.end() >= total_match.start():
        raise ValueError("Invalid resource area")
    header_text = section[:materials.start()]
    if not re.search(r"Ölçü Birimi[ \t]*\r?\n[ \t]*m³[ \t]*$", header_text, re.MULTILINE):
        raise ValueError("Expected cubic-metre analysis unit")

    area = section[materials.end():total_match.start()]
    resources = []
    for match in ROW.finditer(area):
        quantity = number(match.group("quantity"))
        price = number(match.group("price"))
        amount = number(match.group("amount"))
        calculated = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if calculated != amount:
            raise ValueError("Auxiliary resource arithmetic mismatch")
        offset = start + materials.end()
        resources.append({
            "code": match.group("code"),
            "description": match.group("description").strip(),
            "unit": match.group("unit"),
            "quantity": str(quantity),
            "unit_price": str(price),
            "amount": str(amount),
            "evidence": evidence(page_text, offset + match.start(), offset + match.end(), pdf_page),
        })

    expected_rows = (
        (sand_code, "m³"),
        ("10.130.1209", "Ton"),
        ("10.130.9991", "m³"),
        ("10.100.1062", "Sa"),
        ("10.100.1062", "Sa"),
    )
    if tuple((row["code"], row["unit"]) for row in resources) != expected_rows:
        raise ValueError("Unexpected or missing auxiliary resources")
    # Every resource-code line must have been parsed, including duplicate workers.
    resource_lines = re.findall(r"(?m)^[ \t]*(\d{2}\.\d{3}\.\d{4})[ \t]*$", area)
    if resource_lines != [row["code"] for row in resources]:
        raise ValueError("Unparsed auxiliary resource rows")
    if Decimal(resources[1]["quantity"]) != cement_tonnes:
        raise ValueError("Unexpected cement quantity")
    total = number(total_match.group(1))
    if sum((Decimal(row["amount"]) for row in resources), Decimal("0")) != total:
        raise ValueError("Auxiliary resource sum differs from stated total")

    return {
        "schema": "arkemx.pdf_auxiliary_source.v1",
        "position_code": position_code,
        "description": title.group(1).strip(),
        "unit": "m³",
        "read_only": True,
        "approval_allowed": False,
        "resources": resources,
        "total": str(total),
        "currency": "TRY",
        "total_basis": "sum_of_published_resource_amounts",
        "additional_overhead_applied": False,
        "analysis_evidence": evidence(page_text, start, start + total_match.end(), pdf_page),
        "total_evidence": evidence(page_text, start + total_match.start(), start + total_match.end(), pdf_page),
        "source": {
            "pdf_page": pdf_page,
            "printed_page": printed_page,
            "price_date": "2026-01-01",
            "page_text": page_text,
        },
    }


def read_auxiliary_analysis(path: str | Path, position_code: str) -> dict:
    """Verify source bytes and read only the supported analysis page."""
    if position_code not in SUPPORTED:
        raise ValueError("Unsupported auxiliary position")
    source = Path(path)
    pdf_bytes = source.read_bytes()
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Auxiliary PDF SHA-256 does not match pilot source")
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        if len(document) != 706:
            raise ValueError("Unexpected auxiliary PDF page count")
        page = SUPPORTED[position_code][0]
        text = document[page - 1].get_text("text", sort=False)
    result = parse_auxiliary_text(text, position_code)
    result["source"].update({"sha256": digest, "filename": source.name, "page_count": 706})
    return result
