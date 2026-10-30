"""Read local 2026 price-analysis PDF tables with fail-closed cost checks.

PDF content stays on the user's server and is never committed or distributed.
The parsed positions are suggestions only, not approved engineering decisions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pymupdf

POSITION_CODE = re.compile(r"15\.\d{3}\.\d{4}\Z")
INPUT_CODE = re.compile(r"(?:10|15|19)\.\d{3}\.\d{4}\Z")
NUMBER = re.compile(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?\Z")
MAX_PAGES = 1800


def number(raw: str | None) -> Decimal | None:
    if raw is None or not NUMBER.fullmatch(raw):
        return None
    try:
        return Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def normalize_unit(raw: str) -> str:
    return {"Ton": "ton", "Ad": "adet", "Kg": "kg", "Sa": "sa"}.get(raw.strip(), raw.strip())


@dataclass(frozen=True)
class PdfPosition:
    id: str
    description: str
    unit: str
    price: Decimal
    price_verified: bool
    pdf_page: int
    ingredients: tuple[dict, ...]
    scope: str


def _page_positions(page, number_: int) -> list[PdfPosition]:
    words = page.get_text("words", sort=False)
    headings = sorted(
        (w for w in words if w[4] == "Analizin" and 250 < w[0] < 320 and w[1] < 790),
        key=lambda w: w[1],
    )
    positions = []
    for i, heading in enumerate(headings):
        start = heading[1]
        end = headings[i + 1][1] if i + 1 < len(headings) else 780
        codes = [
            w for w in words if start + 12 < w[1] < min(start + 90, end)
            and w[0] < 95 and POSITION_CODE.fullmatch(w[4])
        ]
        subheaders = [
            w for w in words if start + 14 < w[1] < start + 94
            and 135 < w[0] < 250 and w[4] == "Tanımı"
        ]
        if not codes or not subheaders:
            continue
        head_y = subheaders[0][1]
        if head_y < codes[0][1]:
            continue
        descr = " ".join(
            w[4] for w in sorted(
                (w for w in words if start + 10 < w[1] < head_y - 2 and 98 < w[0] < 505),
                key=lambda w: (round(w[1] / 5), w[0]),
            )
        )
        units = [w for w in words if start + 10 < w[1] < head_y - 2 and 504 < w[0] < 558]
        if not descr or not units:
            continue
        raw_unit = " ".join(w[4] for w in sorted(units, key=lambda w: (w[1], w[0])))
        subtotal_y = None
        for item in words:
            if item[4] != "Malzeme" or not (98 < item[0] < 155 and head_y < item[1] < end):
                continue
            line = [w[4] for w in words if abs(w[1] - item[1]) < 3 and 100 < w[0] < 285]
            if "+" in line and "Tutarı" in line:
                subtotal_y = item[1]
                break
        if subtotal_y is None:
            continue
        price_line = [
            w for w in words if w[4] == "Fiyatı" and 105 < w[0] < 300
            and subtotal_y + 14 < w[1] < min(subtotal_y + 58, end - 5)
        ]
        if not price_line:
            continue
        y_price = price_line[0][1]
        price_values = [
            w[4] for w in words if abs(w[1] - y_price) < 4
            and 500 < w[0] < 579 and NUMBER.fullmatch(w[4])
        ]
        price = number(price_values[-1]) if price_values else None
        if price is None:
            continue
        inputs = []
        for code in words:
            if not INPUT_CODE.fullmatch(code[4]) or code[0] >= 95 or not head_y + 7 < code[1] < subtotal_y - 3:
                continue
            line = [w for w in words if abs(w[1] - code[1]) < 3.3]
            fields = {
                "description": (101, 305), "unit": (305, 351),
                "quantity": (351, 423), "unit_price": (423, 504), "amount": (504, 581),
            }
            record = {"code": code[4]}
            for field, (x0, x1) in fields.items():
                vals = [w[4] for w in sorted(line, key=lambda w: w[0]) if x0 <= w[0] < x1]
                record[field] = (
                    " ".join(vals) if field in ("description", "unit")
                    else (vals[-1] if vals else None)
                )
            inputs.append(record)
        if not inputs:
            continue
        amounts = [number(entry["amount"]) for entry in inputs]
        computed = (
            (sum(amounts) * Decimal("1.25")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
            if all(value is not None for value in amounts) else None
        )
        # Extra indirect cost lines (%3 for scaffolding, etc.) are currently
        # deliberately unverified rather than silently guessed or discarded.
        verified = computed is not None and abs(price - computed) <= Decimal("0.04")
        scope = page.get_text(
            "text", clip=pymupdf.Rect(36, y_price + 14, 575, min(end, 740)), sort=True,
        ).strip()[:1500]
        positions.append(PdfPosition(
            id=codes[0][4], description=" ".join(descr.split()),
            unit=normalize_unit(raw_unit), price=price, price_verified=verified,
            pdf_page=number_, ingredients=tuple(inputs), scope=scope,
        ))
    return positions


def read_positions(pdf_bytes: bytes) -> list[PdfPosition]:
    if not pdf_bytes.startswith(b"%PDF-") or len(pdf_bytes) > 16 * 1024 * 1024:
        raise ValueError("Invalid or oversized PDF")
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass or not 10 <= len(document) <= MAX_PAGES:
                raise ValueError("Unsupported PDF structure")
            if "1.01.2026" not in document[5].get_text():
                raise ValueError("Not the expected 2026 analysis edition")
            positions = [
                p for page_i, page in enumerate(document)
                for p in _page_positions(page, page_i + 1)
            ]
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise ValueError("Unreadable PDF file") from exc
    if len(positions) < 50 or len({p.id for p in positions}) != len(positions):
        raise ValueError("PDF analysis table structure not supported")
    return positions
