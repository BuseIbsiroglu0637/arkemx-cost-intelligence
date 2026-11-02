"""A3.48.1: read a user-provided 2026 YFK price list into a local catalog.

This price list is NOT the detailed unit-price analysis and cannot authorize
engineering approval or estimate inclusion. Each value is linked to a PDF page
and SHA; unpriced headings and ambiguous cells remain unpriced.

The source PDF and exported index stay on the user's machine. Do not commit
copyrighted document contents or local index output to the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pymupdf

CODE = re.compile(r"^\d{2}\.\d{3}\.\d{4}$")
MONEY = re.compile(r"^(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}$")
UNIT = re.compile(r"^(?:m|m²|m³|Sa|Ad|Kg|Ton|kWh|lt|L|Çift|Takım|³|²)$", re.I)
MEASUREMENT = re.compile(r"Ölçü\s*:\s*([^.)]+)", re.I)
KIND = {10: "rayic", 15: "insaat", 25: "mekanik", 35: "elektrik"}
SOURCE_DATE = "01.01.2026"
MAX_BYTES = 30 * 1024 * 1024
MAX_PAGES = 1500


def money(value: str) -> str | None:
    if not MONEY.fullmatch(value):
        return None
    try:
        result = Decimal(value.replace(".", "").replace(",", "."))
        return f"{result:.2f}" if result > 0 else None
    except InvalidOperation:
        return None


def _row_boundaries(page) -> list[float]:
    """The supplied tariff PDF uses drawn table gridlines across columns."""
    levels = set()
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if (item[0] == "l" and abs(item[1].y - item[2].y) <= 0.6
                    and abs(item[1].x - item[2].x) >= 200):
                y = item[1].y
                if 60 < y < 812:
                    levels.add(round(y, 1))
    return sorted(levels)


def _parse_row(code_word: tuple, words: list[tuple], bounds: list[float],
               page_number: int) -> tuple[dict[str, Any] | None, str]:
    code = code_word[4]
    kind = KIND.get(int(code[:2]))
    if not kind:
        return None, "unknown_code_family"
    y = code_word[1]
    bottom = max((v for v in bounds if v <= y), default=None)
    top = min((v for v in bounds if v > y), default=None)
    if bottom is None or top is None or top <= bottom:
        return None, "no_row_borders"
    # Some valid mechanical/electrical descriptions occupy almost a whole
    # PDF page. A fixed 320-point height cap silently dropped 18 official
    # code rows despite BOTH observed grid lines being present. Keep the
    # observed boundaries, but refuse to mix two codes in one inferred row.
    row = [w for w in words if bottom - 1 <= w[1] < top - 1 and w[0] > 37]
    row_codes = [w[4] for w in row if 38 <= w[0] < 65 and CODE.fullmatch(w[4])]
    if row_codes != [code]:
        return None, "ambiguous_row_boundaries"
    # Material rayics use x=427 for units; construction and labor use x=489.
    material_unit = any(415 <= w[0] < 448 and abs(w[1] - y) < 4
                        and UNIT.fullmatch(w[4]) for w in row)
    description_right = 414 if kind == "rayic" and material_unit else (
        476 if kind in ("rayic", "insaat") else 452
    )
    description_words = [w for w in row if 108 <= w[0] < description_right
                         and w[4] != code]
    description_words.sort(key=lambda w: (round(w[1] / 3), w[0]))
    description = " ".join(w[4] for w in description_words).strip()
    if not description:
        return None, "no_description"

    unit = None
    prices = [w for w in row if MONEY.fullmatch(w[4])]
    if kind in ("rayic", "insaat"):
        main_cells = [w for w in prices if w[0] > 510]
        install_cells: list[tuple] = []
        unit_cells = [w for w in row if abs(w[1] - y) < 4
                      and ((410 <= w[0] < 448) if material_unit else
                           (478 <= w[0] < 505)) and UNIT.fullmatch(w[4])]
        unit = "".join(w[4] for w in sorted(unit_cells, key=lambda w: w[0])) or None
    else:
        # Mechanical/electrical tables have mounted price and separate
        # installation fee. They do not have per-row verified unit cells.
        main_cells = [w for w in prices if 450 <= w[0] and w[2] < 525]
        install_cells = [w for w in prices if w[0] >= 520]
    uncertain = len(main_cells) > 1 or len(install_cells) > 1
    main = money(main_cells[0][4]) if len(main_cells) == 1 and not uncertain else None
    installation = (money(install_cells[0][4])
                    if len(install_cells) == 1 and not uncertain else None)
    state = "ambiguous_price" if uncertain else ("cell_extracted" if main else "unpriced")
    return {
        "code": code, "description": description, "unit": unit,
        "kind": kind, "unit_price": main,
        "installation_price": installation, "price_status": state,
        "pdf_page": page_number, "row_y": [bottom, top],
        "parent_code": None, "parent_description": None,
        "unit_hint": None, "cost_allowed": False,
    }, "ok"


def ingest_pdf(raw: bytes) -> dict[str, Any]:
    """Read-only audited index. Never writes to the project or M5 tables."""
    if not raw.startswith(b"%PDF-") or not 100_000 <= len(raw) <= MAX_BYTES:
        raise ValueError("Expected a readable price list PDF (100KB to 30MB)")
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        if doc.needs_pass or not 10 <= len(doc) <= MAX_PAGES:
            raise ValueError("Unsupported or encrypted PDF")
        # Fail closed rather than mislabel a newer/older year's prices as 2026.
        sample = " ".join(doc[i].get_text("text") for i in range(5, min(11, len(doc))))
        if SOURCE_DATE not in sample:
            raise ValueError("Source is not the expected 01.01.2026 price-list edition")
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        observed = Counter()
        parent: dict[str, dict[str, Any]] = {}
        for page in doc:
            words = page.get_text("words", sort=False)
            codes = [w for w in words if 38 <= w[0] < 65 and CODE.fullmatch(w[4])]
            bounds = _row_boundaries(page)
            for word in codes:
                observed["codes_seen"] += 1
                record, error = _parse_row(word, words, bounds, page.number + 1)
                if record is None:
                    failures.append({
                        "code": word[4], "pdf_page": page.number + 1, "reason": error,
                    })
                    continue
                observed["records_extracted"] += 1
                observed[record["kind"]] += 1
                observed[record["price_status"]] += 1
                group = record["code"][:9]
                # A heading may supply description search context, NOT pricing.
                if (record["kind"] in ("mekanik", "elektrik") and
                        record["code"].endswith("00") and record["unit_price"] is None):
                    parent[group] = record
                elif record["kind"] in ("mekanik", "elektrik") and group in parent:
                    heading = parent[group]
                    record["parent_code"] = heading["code"]
                    record["parent_description"] = heading["description"][:260]
                    unit_match = MEASUREMENT.search(heading["description"])
                    if unit_match:
                        record["unit_hint"] = unit_match.group(1).strip()
                records.append(record)
        counts = Counter(row["code"] for row in records)
        duplicate_codes = sorted(code for code, total in counts.items() if total > 1)
        return {
            "schema": "arkemx.a348.official_price_catalog.v1",
            "source_kind": "user_supplied_2026_yfk_price_list",
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "edition_date": SOURCE_DATE, "pdf_pages": len(doc),
            "read_only": True, "approval_allowed": False, "cost_allowed": False,
            "records": records,
            "audit": {
                "codes_seen": observed["codes_seen"],
                "records_extracted": observed["records_extracted"],
                "unparsed_count": len(failures),
                "by_kind": {kind: observed[kind] for kind in KIND.values()},
                "price_cells_extracted": observed["cell_extracted"],
                "unpriced_count": observed["unpriced"],
                "ambiguous_price_count": observed["ambiguous_price"],
                "duplicate_code_count": len(duplicate_codes),
                "duplicate_codes_sample": duplicate_codes[:25],
                "unparsed_rows": failures,
                "notes": [
                    "A price-list cell is not a detailed cost analysis or technical approval.",
                    "Mounted prices and installation prices are separate money fields.",
                    "Unpriced headings and unresolved rows must not be priced at zero.",
                    "Only the user-supplied price-list PDF was processed.",
                ],
            },
        }


def export_local(pdf_path: Path, dest: Path) -> dict[str, Any]:
    if dest.exists():
        raise FileExistsError(f"Refusing to overwrite an existing index: {dest}")
    data = ingest_pdf(pdf_path.read_bytes())
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary file exists: {temporary}")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(dest)
    finally:
        temporary.unlink(missing_ok=True)
    return data["audit"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only 2026 YFK price-list index")
    parser.add_argument("pdf", type=Path, help="2026 YFK unit-price list PDF")
    parser.add_argument("--out", type=Path, required=True, help="Local index JSON (new file)")
    args = parser.parse_args()
    print(json.dumps(export_local(args.pdf, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
