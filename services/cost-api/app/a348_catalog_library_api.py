"""A3.48.2 — private, PDF-only position library.

Upload the user's 2026 YFK PRICE LIST PDF, index it with A3.48.1 and
browse it without an Excel import, project selection, approval, or M5 writes.
Original PDF and indexes remain in organization-scoped local UPLOAD_DIR.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from .a348_official_price_list import CODE, MAX_BYTES, ingest_pdf
from .models import User
from .security import current_user

router = APIRouter(prefix="/api/a348/catalog", tags=["A3.48 PDF Poz Kütüphanesi"])
NO_STORE = {"Cache-Control": "private, no-store"}
SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")
KIND_FILTERS = {"all", "rayic", "insaat", "mekanik", "elektrik"}


def _base(user: User) -> Path:
    directory = Path(os.getenv("UPLOAD_DIR", "uploads")) / "_a348_official_price_library" / user.organization_id
    # Prevent a symlink from redirecting local user-owned source data.
    if directory.is_symlink() or directory.parent.is_symlink():
        raise HTTPException(409, "Unsafe catalog path", headers=NO_STORE)
    return directory


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _atomic_new(path: Path, data: bytes) -> None:
    # Never replace a previously indexed source file; keep it versioned.
    with path.open("xb") as handle:
        handle.write(data)


def _atomic_pointer(path: Path, data: bytes) -> None:
    # Pointer only. Never change earlier SHA-versioned source PDFs/indexes.
    temp = path.with_suffix(".tmp")
    with temp.open("xb") as handle:
        handle.write(data)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _pointer(user: User) -> tuple[Path, dict] | None:
    root = _base(user)
    path = root / "current.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        sha = info["source_sha256"]
        index_hash = info["index_sha256"]
        if not SAFE_HASH.fullmatch(sha) or not SAFE_HASH.fullmatch(index_hash):
            raise ValueError("Invalid source identifier")
    except (ValueError, KeyError, OSError, TypeError):
        raise HTTPException(409, "Catalog pointer is unreadable", headers=NO_STORE) from None
    return root, info


@lru_cache(maxsize=12)
def _load_index(path: str, expected_hash: str) -> dict:
    location = Path(path)
    if location.is_symlink() or not location.is_file():
        raise ValueError("Index missing")
    raw = location.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("Index has changed")
    data = json.loads(raw)
    if (
        data.get("schema") != "arkemx.a348.official_price_catalog.v1"
        or data.get("read_only") is not True
        or data.get("approval_allowed") is not False
        or data.get("cost_allowed") is not False
        or not isinstance(data.get("records"), list)
        or not isinstance(data.get("audit"), dict)
    ):
        raise ValueError("Unexpected catalog format")
    return data


def _source(user: User) -> dict | None:
    pointer = _pointer(user)
    if not pointer:
        return None
    root, info = pointer
    version_folder = root / info["source_sha256"]
    if version_folder.is_symlink():
        raise HTTPException(409, "Unsafe catalog source version", headers=NO_STORE)
    index_file = version_folder / "catalog.json"
    try:
        data = _load_index(str(index_file), info["index_sha256"])
        if data["source_sha256"] != info["source_sha256"]:
            raise ValueError("Source fingerprint mismatch")
        pdf_file = root / info["source_sha256"] / "source.pdf"
        if not pdf_file.is_file() or pdf_file.is_symlink():
            raise ValueError("Original PDF missing")
    except (OSError, KeyError, ValueError, TypeError):
        raise HTTPException(409, "PDF catalog source could not be verified", headers=NO_STORE) from None
    return data


def _summary(data: dict | None) -> dict:
    if data is None:
        return {"present": False, "read_only": True, "approval_allowed": False, "cost_allowed": False}
    audit = data["audit"]
    return {
        "present": True, "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "source_sha256": data["source_sha256"],
        "edition_date": data["edition_date"],
        "pdf_pages": data["pdf_pages"],
        "total_records": len(data["records"]),
        "audit": {
            "codes_seen": audit["codes_seen"],
            "records_extracted": audit["records_extracted"],
            "unparsed_count": audit["unparsed_count"],
            "unpriced_count": audit["unpriced_count"],
            "price_cells_extracted": audit["price_cells_extracted"],
            "ambiguous_price_count": audit["ambiguous_price_count"],
            "duplicate_code_count": audit["duplicate_code_count"],
            "by_kind": audit["by_kind"],
        },
    }


@router.get("/source")
def catalog_source(response: Response, user: Annotated[User, Depends(current_user)]):
    response.headers.update(NO_STORE)
    return _summary(_source(user))


@router.post("/source", status_code=201)
async def upload_catalog_source(
    response: Response, file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(current_user)],
):
    """Rebuild the index locally from the *actual PDF*, not unverified JSON."""
    try:
        raw = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "PDF exceeds the permitted size", headers=NO_STORE)
    try:
        data = ingest_pdf(raw)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc), headers=NO_STORE) from exc
    if (data["audit"]["unparsed_count"] > 0 or
            data["audit"]["codes_seen"] != len(data["records"]) or
            data["audit"]["duplicate_code_count"] != 0):
        raise HTTPException(
            422, "PDF has unparsed or duplicate position codes; source was not activated",
            headers=NO_STORE,
        )
    root = _base(user)
    sha = data["source_sha256"]
    folder = root / sha
    if folder.is_symlink():
        raise HTTPException(409, "Unsafe catalog source version", headers=NO_STORE)
    folder.mkdir(parents=True, exist_ok=True)
    index = _json_bytes(data)
    index_hash = hashlib.sha256(index).hexdigest()
    for filename, payload in (("source.pdf", raw), ("catalog.json", index)):
        target = folder / filename
        if target.is_symlink():
            raise HTTPException(409, "Unsafe catalog file", headers=NO_STORE)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != hashlib.sha256(payload).hexdigest():
                raise HTTPException(409, "Existing PDF version differs", headers=NO_STORE)
        else:
            try:
                _atomic_new(target, payload)
            except FileExistsError:
                raise HTTPException(409, "Concurrent catalog source update", headers=NO_STORE) from None
    info = {"source_sha256": sha, "index_sha256": index_hash}
    pointer = root / "current.json"
    if pointer.is_symlink():
        raise HTTPException(409, "Unsafe active catalog pointer", headers=NO_STORE)
    try:
        _atomic_pointer(pointer, _json_bytes(info))
    except FileExistsError:
        raise HTTPException(409, "Another source upload is in progress", headers=NO_STORE) from None
    response.headers.update(NO_STORE)
    return _summary(data)


def _normalized(text: str) -> str:
    text = text.replace("ı", "i").replace("İ", "I")
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _score(row: dict, query: str) -> int | None:
    code = row["code"]
    description = _normalized(row["description"])
    group_description = _normalized(row.get("parent_description") or "")
    searchable = f"{code} {description} {group_description}"
    if query == code:
        return 0
    if code.startswith(query):
        return 1
    if description.startswith(query):
        return 2
    if query in description:
        return 3
    if all(word in searchable for word in query.split()):
        return 4
    return None


@router.get("/positions")
def list_catalog_positions(
    response: Response,
    user: Annotated[User, Depends(current_user)],
    q: str = Query(default="", max_length=160),
    kind: str = Query(default="all"),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=40, ge=1, le=100),
):
    if kind not in KIND_FILTERS:
        raise HTTPException(422, "Unsupported position kind", headers=NO_STORE)
    data = _source(user)
    if data is None:
        raise HTTPException(409, "Attach the 2026 price-list PDF first", headers=NO_STORE)
    query = _normalized(q.strip())
    matches: list[tuple[int, dict]] = []
    for record in data["records"]:
        if kind != "all" and record["kind"] != kind:
            continue
        score = _score(record, query) if query else 0
        if score is not None:
            matches.append((score, record))
    if query:
        matches.sort(key=lambda entry: (entry[0], entry[1]["code"]))
    start = (page - 1) * page_size
    response.headers.update(NO_STORE)
    return {
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "source_sha256": data["source_sha256"],
        "total": len(matches), "page": page, "page_size": page_size,
        "items": [record for _, record in matches[start:start + page_size]],
    }
