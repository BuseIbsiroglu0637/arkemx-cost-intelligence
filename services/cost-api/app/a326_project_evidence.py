"""A3.26: project-specific technical specification PDF evidence (local-only pilot).

All evidence is read-only and linked to the PDF SHA and printed PDF page.
A text hit is NOT engineering verification, an accepted position or a price.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import pymupdf
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a318_pdf_api import _read as read_analysis_pdf
from .a324_ceramic_features import ceramic_features
from .database import get_db
from .excel import normalized
from .matching import family
from .models import PdfCandidateSelection, User, WorkItem
from .revisions import effective_item
from .security import current_user
from .technical import extract

router = APIRouter(prefix="/api/projects/{project_id}/a326", tags=["A3.26 Project Evidence"])
FILE_LIMIT = 8 * 1024 * 1024
PAGE_LIMIT = 100
TEXT_LIMIT = 400_000
MAX_MATCH_BLOCKS = 6


def _file_path(user: User, project_id: UUID) -> Path:
    org = str(UUID(user.organization_id))
    root = Path(os.environ.get("UPLOAD_DIR", "./data/uploads")).resolve()
    return root / "_project_evidence" / org / str(project_id) / "specification.pdf"


def _read_file(path: Path):
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        return None
    raw = path.read_bytes()
    return raw, hashlib.sha256(raw).hexdigest()


def _scan(raw: bytes) -> tuple[list[tuple[int, str]], int]:
    """Extract bounded text blocks, preserving 1-based PDF page locations."""
    if not raw.startswith(b"%PDF-") or len(raw) > FILE_LIMIT:
        raise ValueError("Invalid PDF")
    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
        try:
            if doc.needs_pass or len(doc) > PAGE_LIMIT or len(doc) < 1:
                raise ValueError("Encrypted or oversized PDF")
            blocks: list[tuple[int, str]] = []
            total = 0
            for index in range(len(doc)):
                for block in doc[index].get_text("blocks"):
                    if len(block) < 5 or not isinstance(block[4], str):
                        continue
                    text = re.sub(r"\s+", " ", block[4]).strip()
                    if not text:
                        continue
                    total += len(text)
                    if total > TEXT_LIMIT:
                        raise ValueError("Too much PDF text")
                    blocks.append((index + 1, text))
            return blocks, len(doc)
        finally:
            doc.close()
    except (pymupdf.FileDataError, pymupdf.FileNotFoundError, RuntimeError) as exc:
        raise ValueError("PDF could not be read") from exc


def _metadata(path: Path, raw: bytes, pages: int) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    info_path = path.with_suffix(".json")
    name = "Teknik şartname.pdf"
    if info_path.is_file() and not info_path.is_symlink():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            if info.get("sha256") == digest:
                name = str(info.get("filename", name))[:120]
        except (ValueError, OSError):
            pass
    return {"present": True, "filename": name, "sha256": digest,
            "page_count": pages, "read_only": True}


def _block_matches(description: str, blocks: list[tuple[int, str]]) -> list[dict]:
    kind = family(description)
    dims = extract(description)["dimensions"]
    matches = []
    for page, text in blocks:
        plain = normalized(text)
        if kind == "gazbeton":
            if "gazbeton" not in plain:
                continue
            data = extract(text)
            # If either text specifies wall thickness, it must agree.
            metraj_thick = extract(description)["thickness_mm"]
            if data["thickness_mm"] and metraj_thick and data["thickness_mm"] != metraj_thick:
                continue
            facts = {
                "gazbeton_strength_n_mm2": data["gazbeton_strength_n_mm2"],
                "gazbeton_density_kg_m3": data["gazbeton_density_kg_m3"],
            }
            if all(value is None for value in facts.values()):
                continue
        elif kind == "seramik":
            if not any(word in plain for word in ("seramik", "porselen", "karo ")):
                continue
            data = extract(text)
            if dims and data["dimensions"] and dims != data["dimensions"]:
                continue
            facts = ceramic_features(text)
            if not any(facts.values()):
                continue
        else:
            return []
        matches.append({"page": page, "quote": text[:320],
                        "facts": facts})
    return matches


def _evidence_status(matches: list[dict]) -> str:
    if not matches:
        return "not_found"
    fields = {key for match in matches for key in match["facts"]}
    # Distinct explicit values across plausible project blocks are a conflict;
    # missing attributes don't count as evidence of agreement.
    for key in fields:
        values = {str(row["facts"][key]) for row in matches
                  if row["facts"].get(key) is not None}
        if len(values) > 1:
            return "conflicting"
    return "found_for_review"


def _position_consistency(matches: list[dict], position_description: str | None) -> str:
    """Compare explicit facts only; partial matches must not appear verified."""
    if not matches or not position_description:
        return "unverified"
    kind = family(position_description)
    data = (extract(position_description) if kind == "gazbeton"
            else ceramic_features(position_description) if kind == "seramik" else {})
    required = {
        "gazbeton": {"gazbeton_strength_n_mm2", "gazbeton_density_kg_m3"},
        "seramik": {"glaze", "surface", "rectified"},
    }.get(kind, set())
    compared: set[str] = set()
    for match in matches:
        for key, actual in match["facts"].items():
            expected = data.get(key)
            if actual is None or expected is None:
                continue
            compared.add(key)
            if actual != expected:
                return "conflicts"
    return "matches_examined_facts" if required and required <= compared else "unverified"


@router.get("/source")
def project_document_status(
    project_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    from .m2 import tenant_project
    tenant_project(db, user, str(project_id))
    response.headers.update(NO_STORE)
    doc = _read_file(_file_path(user, project_id))
    if not doc:
        return {"present": False, "read_only": True}
    raw, _ = doc
    try:
        _, pages = _scan(raw)
    except ValueError:
        return {"present": False, "read_only": True}
    return _metadata(_file_path(user, project_id), raw, pages)


@router.post("/source", status_code=201)
async def attach_project_document(
    project_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
):
    from .m2 import tenant_project
    tenant_project(db, user, str(project_id))
    if user.role != "admin" or os.environ.get("ENVIRONMENT", "development") != "development":
        raise HTTPException(403, "Project PDF upload is local-admin only")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF technical specifications are supported")
    try:
        raw = await file.read(FILE_LIMIT + 1)
    finally:
        await file.close()
    if len(raw) > FILE_LIMIT:
        raise HTTPException(413, "Technical specification exceeds 8 MB")
    try:
        _, pages = _scan(raw)
    except ValueError as exc:
        raise HTTPException(422, "Unreadable or unsupported PDF") from exc
    path = _file_path(user, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise HTTPException(409, "Untrusted storage location")
    temporary = path.parent / f".technical-{uuid4().hex}.tmp"
    info_path = path.with_suffix(".json")
    try:
        temporary.write_bytes(raw)
        temporary.replace(path)
        info_path.write_text(json.dumps({
            "sha256": hashlib.sha256(raw).hexdigest(),
            "filename": Path(file.filename).name[:120],
        }, ensure_ascii=False), encoding="utf-8")
    finally:
        temporary.unlink(missing_ok=True)
    response.headers.update(NO_STORE)
    return _metadata(path, raw, pages)


@router.get("/imports/{import_id}/items/{work_item_id}/evidence")
def find_project_evidence(
    project_id: UUID,
    import_id: UUID,
    work_item_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(work_item_id), WorkItem.import_id == batch.id,
    ))
    if item is None:
        raise HTTPException(404, "Excel row not found")
    doc = _read_file(_file_path(user, project_id))
    response.headers.update(NO_STORE)
    if not doc:
        return {"status": "no_document", "evidence": [],
                "engineering_approved": False, "cost_allowed": False}
    raw, digest = doc
    try:
        blocks, pages = _scan(raw)
    except ValueError:
        raise HTTPException(422, "Project PDF can no longer be read")
    current = effective_item(db, item)
    matches = _block_matches(current.raw_description, blocks)
    status = "unreadable_text" if not blocks else _evidence_status(matches)
    # Compare only against a currently saved selection and same PDF source.
    selection = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.work_item_id == item.id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
    ))
    comparison = "unverified"
    saved_code = None
    link_status = "no_saved_candidate"
    if selection:
        pdf = read_analysis_pdf(user)
        if not pdf:
            link_status = "analysis_pdf_missing"
        elif selection.pdf_sha256 != pdf[0] or (
            selection.revision_id != current.revision_id
        ):
            link_status = "source_or_revision_changed"
        else:
            pos = next((x for x in pdf[1] if x.id == selection.position_code), None)
            if pos is None:
                link_status = "candidate_not_in_pdf"
            else:
                saved_code = pos.id
                link_status = "current"
                if status == "found_for_review":
                    comparison = _position_consistency(matches, pos.description)
    return {
        "status": status, "document": _metadata(_file_path(user, project_id), raw, pages),
        "source_sha256": digest, "source_row": item.source_row,
        "revision_id": current.revision_id,
        "saved_candidate": saved_code, "candidate_consistency": comparison,
        "candidate_link_status": link_status,
        "evidence": matches[:MAX_MATCH_BLOCKS],
        "additional_evidence_count": max(0, len(matches) - MAX_MATCH_BLOCKS),
        "engineering_approved": False,
        "cost_allowed": False,
    }
