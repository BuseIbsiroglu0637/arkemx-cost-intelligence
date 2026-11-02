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
        data = _read_index(str(version / "analysis.json"), info["index_sha256"])
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


def _observed_headers(raw: bytes) -> dict[str, int]:
    """Count analysis headings only, not reference/input codes inside the text."""
    seen: dict[str, int] = {}
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        for pageno, page in enumerate(pdf, start=1):
            words = page.get_text("words", sort=False)
            headings = [
                w for w in words
                if w[4] == "Analizin" and 250 < w[0] < 320 and w[1] < 790
            ]
            for header in headings:
                nearby = [
                    w[4] for w in words
                    if w[0] < 95 and POSITION_CODE.fullmatch(w[4])
                    and header[1] + 12 < w[1] < header[1] + 90
                ]
                if len(nearby) == 1:
                    seen[nearby[0]] = pageno
    return seen


def _extract(raw: bytes) -> dict:
    positions = read_positions(raw)
    expected = _observed_headers(raw)
    parsed_codes = {position.id for position in positions}
    missing = sorted(set(expected) - parsed_codes)
    records = []
    for position in positions:
        audit = verified_price_audit(position)
        records.append({
            "code": position.id, "description": position.description,
            "unit": position.unit, "analysis_price": str(position.price),
            "analysis_price_reconciled": bool(position.price_verified and audit is not None),
            "analysis_audit": audit,
            "pdf_page": position.pdf_page, "inputs": list(position.ingredients),
            "scope": position.scope,
            "cost_allowed": False,
        })
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        count_pages = len(pdf)
    return {
        "schema": "arkemx.a348.analysis_catalog.v1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "edition_date": "01.01.2026", "pdf_pages": count_pages,
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "records": records,
        "audit": {
            "headers_detected": len(expected),
            "positions_extracted": len(records),
            "unparsed_header_count": len(missing),
            "unparsed_header_codes_sample": [
                {"code": code, "pdf_page": expected[code]} for code in missing[:100]
            ],
            "analysis_price_reconciled_count": sum(
                bool(row["analysis_price_reconciled"]) for row in records
            ),
            "analysis_price_needs_review_count": sum(
                not row["analysis_price_reconciled"] for row in records
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
    for name, payload in (("source.pdf", raw), ("analysis.json", index_bytes)):
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
        }))
    except FileExistsError:
        raise HTTPException(409, "Concurrent analysis source activation", headers=NO_STORE) from None
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
    equal_price = list_price is not None and linked["analysis_price"] is not None and (
        __import__("decimal").Decimal(list_price) == __import__("decimal").Decimal(linked["analysis_price"])
    )
    return {
        **base, "available": True, "reason": None, "analysis": linked,
        "list_analysis_price_equal": equal_price if list_price is not None else None,
        "price_comparison_is_approval": False,
    }
