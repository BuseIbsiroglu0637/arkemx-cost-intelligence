"""A3.48.3: keep a separate 2026 analysis PDF, link by exact poz code.

This module NEVER changes project metraj, engineering approvals, list prices,
or M5 cost. A numeric match is only a document-reference link, not approval.
Copyrighted original PDFs and extracted data stay in a tenant-private folder.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import pymupdf
from fastapi import APIRouter, Depends, File, HTTPException, Path as ApiPath, Response, UploadFile

from .a318_pdf_engine import POSITION_CODE, read_positions, verified_price_audit
from .a348_catalog_library_api import (
    NO_STORE, _atomic_new, _atomic_pointer, _json_bytes, _source as price_list_source,
)
from .models import User
from .security import current_user

router = APIRouter(prefix="/api/a348/catalog", tags=["A3.48.3 PDF Analiz Kütüphanesi"])
MAX_ANALYSIS_PDF_BYTES = 16 * 1024 * 1024
SAFE_SHA = re.compile(r"^[0-9a-f]{64}$")
INDEX_FILE = "analysis-a3484.json"
VALID_INDEX_FILES = {"analysis.json", INDEX_FILE}
FORMULA_CODES = {"15.110.1001", "15.110.1002"}


def _root(user: User) -> Path:
    path = Path(os.getenv("UPLOAD_DIR", "uploads")) / "_a348_official_analysis_library" / user.organization_id
    if path.is_symlink() or path.parent.is_symlink():
        raise HTTPException(409, "Unsafe analysis source path", headers=NO_STORE)
    return path


def _source_pointer(user: User) -> tuple[Path, dict] | None:
    root = _root(user)
    pointer = root / "current.json"
    if pointer.is_symlink():
        raise HTTPException(409, "Unsafe analysis source pointer", headers=NO_STORE)
    if not pointer.is_file():
        return None
    try:
        info = json.loads(pointer.read_text(encoding="utf-8"))
        if not SAFE_SHA.fullmatch(info["source_sha256"]) or not SAFE_SHA.fullmatch(info["index_sha256"]):
            raise ValueError("Bad hash")
        return root, info
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(409, "Analysis source pointer unreadable", headers=NO_STORE) from None


@lru_cache(maxsize=12)
def _read_index(file_path: str, expected_sha: str) -> dict:
    path = Path(file_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Analysis index not available")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Analysis index fingerprint mismatch")
    data = json.loads(raw)
    if (data.get("schema") != "arkemx.a348.analysis_catalog.v1"
            or data.get("read_only") is not True
            or data.get("approval_allowed") is not False
            or data.get("cost_allowed") is not False
            or not isinstance(data.get("records"), list)):
        raise ValueError("Invalid analysis index")
    return data


def _source(user: User) -> dict | None:
    pointer = _source_pointer(user)
    if pointer is None:
        return None
    root, info = pointer
    version = root / info["source_sha256"]
    if version.is_symlink():
        raise HTTPException(409, "Unsafe analysis version directory", headers=NO_STORE)
    try:
        filename = info.get("index_file", "analysis.json")
        if filename not in VALID_INDEX_FILES:
            raise ValueError("Unexpected index version")
        data = _read_index(str(version / filename), info["index_sha256"])
        original = version / "source.pdf"
        if (data["source_sha256"] != info["source_sha256"]
                or not original.is_file() or original.is_symlink()):
            raise ValueError("Analysis PDF is not available")
        return data
    except (OSError, KeyError, ValueError, TypeError):
        raise HTTPException(409, "Analysis source could not be verified", headers=NO_STORE) from None


def _summary(data: dict | None) -> dict:
    if data is None:
        return {
            "present": False, "read_only": True,
            "approval_allowed": False, "cost_allowed": False,
        }
    return {
        "present": True, "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "source_sha256": data["source_sha256"],
        "edition_date": data["edition_date"],
        "pdf_pages": data["pdf_pages"],
        "position_count": len(data["records"]),
        "audit": data["audit"],
    }


def _observed_headers(raw: bytes) -> tuple[dict[str, int], int, int]:
    """Count all actual header blocks; reject neither multi-line nor reference text.

    Some pages mention an *additional* position code in the technical scope
    immediately below the header. For diagnostic purposes the nearest code
    after each header is the candidate; report these ambiguous areas too.
    """
    seen: dict[str, int] = {}
    total_headings = 0
    ambiguous_near_header = 0
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        for pageno, page in enumerate(pdf, start=1):
            words = page.get_text("words", sort=False)
            headings = [
                w for w in words
                if w[4] == "Analizin" and 250 < w[0] < 320 and w[1] < 790
            ]
            for header in headings:
                total_headings += 1
                nearby = sorted((
                    w for w in words
                    if w[0] < 95 and POSITION_CODE.fullmatch(w[4])
                    and header[1] + 12 < w[1] < header[1] + 90
                ), key=lambda w: w[1])
                if len(nearby) > 1:
                    ambiguous_near_header += 1
                if nearby:
                    seen[nearby[0][4]] = pageno
    return seen, total_headings, ambiguous_near_header


def _formula_only_entries(
    raw: bytes, missing: set[str], observed: dict[str, int],
) -> list[dict]:
    """Preserve the two PDF-specific depth-surcharge formulas without a fake TL price.

    These are not missing numeric prices: both *official analysis PDF* tables
    leave the money cells blank because H and K are project parameters.
    Only accept an exact printed header code and formula with no value in
    the final price cell. Do not generalize this fallback to arbitrary PDF text.
    """
    recovered: list[dict] = []
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        for code in sorted(FORMULA_CODES & missing):
            page_number = observed.get(code)
            if page_number is None:
                continue
            page = doc[page_number - 1]
            words = page.get_text("words", sort=False)
            code_words = [w for w in words if w[4] == code and w[0] < 95]
            if len(code_words) != 1:
                continue
            code_word = code_words[0]
            headings = sorted(
                (w for w in words if w[4] == "Analizin" and 250 < w[0] < 320),
                key=lambda w: w[1],
            )
            header = next((w for w in reversed(headings) if w[1] < code_word[1]), None)
            if header is None or not 12 < code_word[1] - header[1] < 90:
                continue
            end = next((w[1] for w in headings if w[1] > header[1]), 780)
            subhead = next(
                (w for w in words if w[4] == "Tanımı"
                 and 135 < w[0] < 250 and code_word[1] < w[1] < end),
                None,
            )
            if subhead is None:
                continue
            description = " ".join(
                w[4] for w in sorted(
                    (w for w in words if code_word[1] - 3 < w[1] < subhead[1] - 2
                     and 98 < w[0] < 505),
                    key=lambda w: (round(w[1] / 5), w[0]),
                )
            ).strip()
            unit_words = [
                w for w in words if 504 < w[0] < 558
                and abs(w[1] - code_word[1]) < 5
            ]
            unit = " ".join(w[4] for w in sorted(unit_words, key=lambda w: w[0]))
            text = page.get_text(
                "text",
                clip=pymupdf.Rect(35, header[1], 580, min(end, 780)),
                sort=True,
            )
            compact = re.sub(r"\s+", "", text).replace("×", "x")
            if not re.search(r"F=Mx\(H-2\)xK", compact, re.I):
                continue
            m = re.search(r"\bM\s*:\s*(0,\d+)", text)
            if not m or unit.strip() != "m³":
                continue
            # The final price line is present but the printed value is empty.
            final_prices = [
                w for w in words
                if w[4] == "Fiyatı" and header[1] < w[1] < end
                and 105 < w[0] < 300
            ]
            if not final_prices:
                continue
            last_y = final_prices[-1][1]
            if any(
                re.fullmatch(r"[\d.,]+", w[4]) and 500 < w[0] < 579
                for w in words if abs(w[1] - last_y) < 4
            ):
                continue
            recovered.append({
                "code": code, "description": description, "unit": unit,
                "analysis_price": None, "analysis_price_reconciled": False,
                "analysis_audit": None, "analysis_kind": "parameterized_formula",
                "formula": "F = M × (H − 2) × K",
                "formula_parameters": {"M": m.group(1), "H": None, "K": None},
                "description_status": "from_analysis_pdf",
                "pdf_page": page_number, "inputs": [],
                "scope": text.strip()[:2500], "cost_allowed": False,
            })
    return recovered


def _extract(raw: bytes) -> dict:
    positions = read_positions(raw)
    expected, heading_count, ambiguous_header_count = _observed_headers(raw)
    parsed_codes = {position.id for position in positions}
    missing = sorted(set(expected) - parsed_codes)
    formula_entries = _formula_only_entries(raw, set(missing), expected)
    records = []
    for position in positions:
        audit = verified_price_audit(position)
        records.append({
            "code": position.id, "description": position.description,
            "unit": position.unit, "analysis_price": str(position.price),
            "analysis_kind": "fixed_price",
            "formula": None, "formula_parameters": None,
            "description_status": "from_analysis_pdf" if position.description else "blank_pdf_title",
            "analysis_price_reconciled": bool(position.price_verified and audit is not None),
            "analysis_audit": audit,
            "pdf_page": position.pdf_page, "inputs": list(position.ingredients),
            "scope": position.scope,
            "cost_allowed": False,
        })
    records.extend(formula_entries)
    unresolved = sorted(set(missing) - {entry["code"] for entry in formula_entries})
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        count_pages = len(pdf)
    return {
        "schema": "arkemx.a348.analysis_catalog.v1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "edition_date": "01.01.2026", "pdf_pages": count_pages,
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "records": records,
        "audit": {
            "headers_detected": heading_count,
            "position_codes_detected": len(expected),
            "ambiguous_near_header_count": ambiguous_header_count,
            "positions_extracted": len(records),
            "unparsed_header_count": len(unresolved) + max(0, heading_count - len(expected)),
            "unparsed_header_codes_sample": [
                {"code": code, "pdf_page": expected[code]} for code in unresolved[:100]
            ],
            "parameterized_formula_count": len(formula_entries),
            "missing_analysis_title_count": sum(
                row["description_status"] == "blank_pdf_title" for row in records
            ),
            "analysis_price_reconciled_count": sum(
                bool(row["analysis_price_reconciled"]) for row in records
            ),
            "analysis_price_needs_review_count": sum(
                row["analysis_kind"] == "fixed_price" and not row["analysis_price_reconciled"]
                for row in records
            ),
            "notes": [
                "Analysis Cilt 1 is not the complete price list or other analysis volumes.",
                "A linked code is not technical compatibility or an approved cost.",
                "Unparsed headings and unreconciled values remain unverified.",
            ],
        },
    }


@router.get("/analysis/source")
def get_analysis_source(response: Response, user: Annotated[User, Depends(current_user)]):
    response.headers.update(NO_STORE)
    return _summary(_source(user))


@router.post("/analysis/source", status_code=201)
async def upload_analysis_source(
    response: Response,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(current_user)],
):
    try:
        raw = await file.read(MAX_ANALYSIS_PDF_BYTES + 1)
    finally:
        await file.close()
    if len(raw) > MAX_ANALYSIS_PDF_BYTES:
        raise HTTPException(413, "Analysis PDF too large", headers=NO_STORE)
    try:
        data = _extract(raw)
    except (ValueError, RuntimeError, pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise HTTPException(422, str(exc), headers=NO_STORE) from exc
    root = _root(user)
    version = root / data["source_sha256"]
    if version.is_symlink():
        raise HTTPException(409, "Unsafe analysis version directory", headers=NO_STORE)
    version.mkdir(parents=True, exist_ok=True)
    index_bytes = _json_bytes(data)
    index_hash = hashlib.sha256(index_bytes).hexdigest()
    for name, payload in (("source.pdf", raw), (INDEX_FILE, index_bytes)):
        target = version / name
        if target.is_symlink():
            raise HTTPException(409, "Unsafe analysis file", headers=NO_STORE)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(payload).digest():
                raise HTTPException(409, "Existing analysis source differs", headers=NO_STORE)
        else:
            try:
                _atomic_new(target, payload)
            except FileExistsError:
                raise HTTPException(409, "Concurrent analysis upload", headers=NO_STORE) from None
    pointer = root / "current.json"
    if pointer.is_symlink():
        raise HTTPException(409, "Unsafe analysis pointer", headers=NO_STORE)
    try:
        _atomic_pointer(pointer, _json_bytes({
            "source_sha256": data["source_sha256"], "index_sha256": index_hash,
            "index_file": INDEX_FILE,
        }))
    except FileExistsError:
        raise HTTPException(409, "Concurrent analysis source activation", headers=NO_STORE) from None
    response.headers.update(NO_STORE)
    return _summary(data)


@router.post("/analysis/reindex")
def reindex_existing_analysis_pdf(
    response: Response, user: Annotated[User, Depends(current_user)],
):
    """Upgrade the local analysis index using its verified stored source PDF.

    Keep the previous analysis.json untouched; put the new index under
    analysis-a3484.json and atomically update only current.json. The user
    does not need to reupload the same copyrighted PDF.
    """
    pointer = _source_pointer(user)
    if pointer is None:
        raise HTTPException(409, "Upload an analysis PDF first", headers=NO_STORE)
    root, info = pointer
    folder = root / info["source_sha256"]
    if folder.is_symlink():
        raise HTTPException(409, "Unsafe analysis source folder", headers=NO_STORE)
    original = folder / "source.pdf"
    if original.is_symlink() or not original.is_file():
        raise HTTPException(409, "Source PDF missing", headers=NO_STORE)
    raw = original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != info["source_sha256"]:
        raise HTTPException(409, "Source PDF fingerprint does not match", headers=NO_STORE)
    try:
        data = _extract(raw)
    except (ValueError, RuntimeError, pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise HTTPException(422, str(exc), headers=NO_STORE) from exc
    payload = _json_bytes(data)
    target = folder / INDEX_FILE
    if target.is_symlink():
        raise HTTPException(409, "Unsafe new index path", headers=NO_STORE)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(payload).digest():
            raise HTTPException(409, "Indexed version already exists with different data", headers=NO_STORE)
    else:
        try:
            _atomic_new(target, payload)
        except FileExistsError:
            raise HTTPException(409, "Another index rebuild is in progress", headers=NO_STORE) from None
    try:
        _atomic_pointer(root / "current.json", _json_bytes({
            "source_sha256": data["source_sha256"],
            "index_sha256": hashlib.sha256(payload).hexdigest(),
            "index_file": INDEX_FILE,
        }))
    except FileExistsError:
        raise HTTPException(409, "Another catalog refresh is in progress", headers=NO_STORE) from None
    response.headers.update(NO_STORE)
    return _summary(data)


@router.get("/positions/{code}/analysis")
def get_position_analysis(
    response: Response, user: Annotated[User, Depends(current_user)],
    code: str = ApiPath(min_length=11, max_length=11),
):
    if not POSITION_CODE.fullmatch(code):
        raise HTTPException(422, "Invalid construction poz code", headers=NO_STORE)
    catalog = price_list_source(user)
    if catalog is None:
        raise HTTPException(409, "Upload the 2026 price-list PDF first", headers=NO_STORE)
    catalog_position = next((row for row in catalog["records"] if row["code"] == code), None)
    if catalog_position is None:
        raise HTTPException(404, "Poz not in the current price-list PDF", headers=NO_STORE)
    analysis = _source(user)
    response.headers.update(NO_STORE)
    base = {
        "code": code, "read_only": True,
        "approval_allowed": False, "cost_allowed": False,
        "price_list_sha256": catalog["source_sha256"],
        "analysis_source_sha256": analysis["source_sha256"] if analysis else None,
        "price_list_pdf_page": catalog_position["pdf_page"],
        "list_unit": catalog_position["unit"],
        "list_price": catalog_position["unit_price"],
    }
    if analysis is None:
        return {**base, "available": False, "reason": "analysis_pdf_not_uploaded", "analysis": None}
    linked = next((row for row in analysis["records"] if row["code"] == code), None)
    if linked is None:
        return {**base, "available": False, "reason": "analysis_not_in_cilt_1_or_not_parsed", "analysis": None}
    # Comparing equal numbers is documentary consistency only; not a technical
    # or cost approval. Rates can differ between analysis and price-list PDFs.
    list_price = catalog_position["unit_price"]
    equal_price = (
        Decimal(list_price) == Decimal(linked["analysis_price"])
        if list_price is not None and linked["analysis_price"] is not None
        else None
    )
    return {
        **base, "available": True, "reason": None, "analysis": linked,
        "list_analysis_price_equal": equal_price,
        "price_comparison_is_approval": False,
    }


@router.get("/linkage")
def get_pdf_linkage_audit(response: Response, user: Annotated[User, Depends(current_user)]):
    """Actual exact-code join report, not just imported PDF counts.

    Works without a project or metraj, and does not write any decisions or
    mutate either PDF index. If one source is absent, returns a clear status.
    """
    price_data = price_list_source(user)
    analysis_data = _source(user)
    response.headers.update(NO_STORE)
    if price_data is None or analysis_data is None:
        return {
            "read_only": True, "approval_allowed": False, "cost_allowed": False,
            "ready": False, "price_list_present": price_data is not None,
            "analysis_present": analysis_data is not None,
            "linked_count": 0, "catalog_total": len(price_data["records"]) if price_data else 0,
            "analysis_total": len(analysis_data["records"]) if analysis_data else 0,
        }

    prices = {row["code"]: row for row in price_data["records"]}
    analyses = {row["code"]: row for row in analysis_data["records"]}
    linked = sorted(prices.keys() & analyses.keys())
    unlinked_analyses = sorted(analyses.keys() - prices.keys())
    different_prices = []
    unpriced = 0
    formulas = 0
    for code in linked:
        price_value = prices[code]["unit_price"]
        analysis_value = analyses[code]["analysis_price"]
        if analysis_value is None:
            formulas += 1
        if price_value is None:
            unpriced += 1
        elif analysis_value is not None and Decimal(price_value) != Decimal(analysis_value):
            different_prices.append(code)
    return {
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "ready": True,
        "price_list_present": True, "analysis_present": True,
        "price_list_sha256": price_data["source_sha256"],
        "analysis_source_sha256": analysis_data["source_sha256"],
        "catalog_total": len(prices), "analysis_total": len(analyses),
        "linked_count": len(linked),
        "catalog_without_cilt1_analysis_count": len(prices) - len(linked),
        "analyses_without_catalog_code_count": len(unlinked_analyses),
        "analyses_without_catalog_code_sample": unlinked_analyses[:12],
        "linked_without_list_price_count": unpriced,
        "linked_formula_only_count": formulas,
        "linked_price_difference_count": len(different_prices),
        "linked_price_difference_sample": different_prices[:12],
        "example_link": next((code for code in ("15.225.1004", "15.100.1001") if code in linked), linked[0] if linked else None),
        "note": "A numeric-code match shows a PDF document link, not technical approval or M5 pricing.",
    }
