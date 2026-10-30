"""A3.18: user-authorized, local-only direct PDF source for automatic matching.

The actual PDF remains in the organization's local upload area, outside Git.
No synthetic catalog fallback, no engineering approval, no cost postings.
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source, _source_view
from .a318_pdf_engine import PdfPosition, read_positions
from .a324_ceramic_features import ceramic_finish_conflict, ceramic_question
from .a320_smart_matching import (
    enrich_technical,
    find_pdf_candidates,
    issue_summary,
    potential_plaster_pairs,
)
from .database import get_db
from .m2 import tenant_project
from .matching import family
from .models import ImportBatch, PdfCandidateSelection, User, WorkItem, now_utc
from .revisions import effective_item
from .security import current_user
from .technical import compare

router = APIRouter(prefix="/api/projects/{project_id}/a318", tags=["A3.18 Local PDF Analysis"])
PDF_LIMIT = 16 * 1024 * 1024
MAX_ROWS = 20


class SavePdfCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_code: str = Field(pattern=r"^15\.\d{3}\.\d{4}$")
    expected_revision_id: UUID | None
    expected_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def _pdf_candidate_check(current, position: PdfPosition,
                         *, plaster_partner_rows: list[int] | None = None) -> dict:
    """Separate missing metraj inputs from contradictory technical attributes.

    A missing/ambiguous quantity requires review, but it is not evidence
    that a proposed material or finish is technically incompatible.
    """
    check = compare(
        current.raw_description, current.normalized_unit,
        position.description, position.unit,
        quantity_known=current.quantity is not None,
        review_required=current.review_required,
    )
    check = enrich_technical(
        current.raw_description, position.description, check,
        plaster_partner_rows=plaster_partner_rows,
    )
    if "METRAJ_REVIEW_REQUIRED" in check["blockers"]:
        blockers = sorted(set(check["blockers"]) - {"METRAJ_REVIEW_REQUIRED"})
        flags = sorted(set(check["review_flags"]) | {"METRAJ_INPUT_REVIEW_REQUIRED"})
        check = {
            **check, "blockers": blockers, "review_flags": flags,
            "status": "blocked" if blockers else "review",
            "manual_approval_allowed": False,
        }
    return check


def _technical_status(current, position: PdfPosition) -> str:
    return _pdf_candidate_check(current, position)["status"]


def _saved_choice_blocked(current, row: PdfCandidateSelection,
                         by_code: dict[str, PdfPosition]) -> bool:
    position = by_code.get(row.position_code)
    if position is None:
        return True
    if _technical_status(current, position) == "blocked":
        return True
    # The material class must be positively grounded for ceramic finishes.
    return (family(current.raw_description) == "seramik"
            and (family(position.description) != "seramik" or
                 ceramic_finish_conflict(current.raw_description, position.description)))


def _selected_view(row: PdfCandidateSelection, *, current_revision: str | None,
                   current_pdf_sha: str, technically_blocked: bool = False) -> dict:
    valid = (
        row.revision_id == current_revision
        and row.pdf_sha256 == current_pdf_sha
        and not technically_blocked
    )
    return {
        "code": row.position_code if valid else None,
        "current": valid,
        "stale": not valid,
        "stale_reason": "TECHNICAL_CONFLICT" if technically_blocked else
            "SOURCE_OR_REVISION_CHANGED" if not valid else None,
        "revision_id": row.revision_id if valid else None,
        "pdf_sha256": row.pdf_sha256 if valid else None,
        "saved_at": row.saved_at.isoformat() if valid else None,
        "engineering_approved": False,
        "cost_allowed": False,
    }


@router.post("/imports/{import_id}/items/{work_item_id}/candidate", status_code=200)
def save_pdf_candidate(
    project_id: UUID,
    import_id: UUID,
    work_item_id: UUID,
    payload: SavePdfCandidateRequest,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(work_item_id), WorkItem.import_id == batch.id,
    ))
    if item is None:
        raise HTTPException(404, "Metraj row not found", headers=NO_STORE)
    found = _read(user)
    if not found:
        raise HTTPException(409, "PDF source is missing", headers=NO_STORE)
    digest, positions = found
    if digest != payload.expected_pdf_sha256:
        raise HTTPException(409, "PDF changed; refresh suggestions before saving", headers=NO_STORE)
    current = effective_item(db, item)
    if current.revision_id != (str(payload.expected_revision_id) if payload.expected_revision_id else None):
        raise HTTPException(409, "Metraj revision changed; refresh before saving", headers=NO_STORE)
    # Never save an invented/unsupported poz: the code must be in this exact uploaded PDF.
    by_code = {position.id: position for position in positions}
    position = by_code.get(payload.position_code)
    if position is None:
        raise HTTPException(422, "Poz code is not present in this PDF source", headers=NO_STORE)
    if _technical_status(current, position) == "blocked" or (
        family(current.raw_description) == "seramik" and (
            family(position.description) != "seramik" or
            ceramic_finish_conflict(current.raw_description, position.description)
        )
    ):
        raise HTTPException(
            422, "Candidate contradicts the metraj material or technical properties",
            headers=NO_STORE,
        )

    existing = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.work_item_id == item.id,
    ).with_for_update())
    if existing is None:
        existing = PdfCandidateSelection(
            organization_id=user.organization_id, project_id=batch.project_id,
            import_id=batch.id, work_item_id=item.id,
        )
        db.add(existing)
    existing.position_code = payload.position_code
    existing.pdf_sha256 = digest
    existing.revision_id = current.revision_id
    existing.selected_by_id = user.id
    existing.saved_at = now_utc()
    db.commit()
    response.headers.update(NO_STORE)
    return {
        "saved": True, "read_only": False, "approval_allowed": False,
        "engineering_approved": False, "cost_allowed": False,
        "work_item_id": item.id, "import_id": batch.id,
        "selection": _selected_view(
            existing, current_revision=current.revision_id, current_pdf_sha=digest,
        ),
    }



def _path(user: User) -> Path:
    # Tenant IDs are UUIDs; never interpolate user-controlled filenames.
    org = str(UUID(user.organization_id))
    root = Path(os.environ.get("UPLOAD_DIR", "./data/uploads")).resolve()
    folder = root / "_pdf_sources" / org
    return folder / "2026-analysis-cilt1.pdf"


def _read(user: User) -> tuple[str, tuple[PdfPosition, ...]] | None:
    path = _path(user)
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        return None
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return digest, _parse(digest, raw)


@lru_cache(maxsize=4)
def _parse(digest: str, raw: bytes) -> tuple[PdfPosition, ...]:
    return tuple(read_positions(raw))


def _summary(found: tuple[str, tuple[PdfPosition, ...]] | None) -> dict:
    if not found:
        return {"present": False, "read_only": True}
    digest, positions = found
    return {
        "present": True, "read_only": True,
        "sha256": digest, "year": 2026, "volume": 1,
        "position_count": len(positions),
        "verified_price_count": sum(p.price_verified for p in positions),
        "uncertain_price_count": sum(not p.price_verified for p in positions),
        "source_type": "user_uploaded_local_pdf",
    }


@router.get("/source")
def source_status(
    project_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    tenant_project(db, user, str(project_id))
    response.headers.update(NO_STORE)
    return _summary(_read(user))


@router.post("/source", status_code=201)
async def attach_pdf(
    project_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    rights_confirmed: Annotated[bool, Form()],
):
    tenant_project(db, user, str(project_id))
    if user.role != "admin":
        raise HTTPException(403, "Only organization admin may attach the PDF")
    if os.environ.get("ENVIRONMENT", "development") != "development":
        raise HTTPException(403, "Local-only PDF pilot is disabled in production")
    if not rights_confirmed:
        raise HTTPException(403, "Confirm your authority to process the copyrighted PDF")
    try:
        raw = await file.read(PDF_LIMIT + 1)
    finally:
        await file.close()
    if len(raw) > PDF_LIMIT:
        raise HTTPException(413, "PDF exceeds the 16 MB local pilot limit")
    if len(raw) < 1024 or not raw.startswith(b"%PDF-"):
        raise HTTPException(422, "Invalid PDF file")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        positions = _parse(digest, raw)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, "Unsupported or incomplete 2026 analysis PDF") from exc
    destination = _path(user)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise HTTPException(409, "Untrusted PDF storage path")
    temporary = destination.parent / f".pdf-{uuid4().hex}.tmp"
    try:
        temporary.write_bytes(raw)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    response.headers.update(NO_STORE)
    return _summary((digest, positions))


@router.get("/imports/{import_id}/suggestions")
def suggestions_from_pdf(
    project_id: UUID,
    import_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
):
    batch: ImportBatch = _source(db, user, str(project_id), str(import_id))
    found = _read(user)
    if not found:
        raise HTTPException(409, "A licensed 2026 PDF source must be attached first")
    digest, positions = found
    by_code = {p.id: p for p in positions}
    # Use the complete metraj to identify possible pairs on different pages.
    # This is an advisory signal only; no quantity aggregation or auto pricing.
    items = db.scalars(select(WorkItem).where(
        WorkItem.import_id == batch.id,
    ).order_by(WorkItem.source_row, WorkItem.id)).all()
    effective = [effective_item(db, item) for item in items]
    partner_rows = potential_plaster_pairs(effective)
    saved_rows = db.scalars(select(PdfCandidateSelection).where(
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.work_item_id.in_([item.id for item in effective[offset:offset + MAX_ROWS]]),
    )).all()
    saved = {row.work_item_id: row for row in saved_rows}
    rows = []
    for current in effective[offset:offset + MAX_ROWS]:
        partners = partner_rows.get(str(current.id), [])
        candidates = find_pdf_candidates(current, positions)
        scored = []
        rejected = 0
        for result in candidates:
            position = by_code[result["position_id"]]
            check = _pdf_candidate_check(
                current, position, plaster_partner_rows=partners,
            )
            # Technical contradictions are not suggestions. The actual PDF
            # record remains available as source evidence but cannot be
            # presented as a recommended or saveable candidate.
            if check["status"] == "blocked" or (
                family(current.raw_description) == "seramik" and (
                    family(position.description) != "seramik" or
                    ceramic_finish_conflict(current.raw_description, position.description)
                )
            ):
                rejected += 1
                continue
            scored.append({
                "code": position.id,
                "description": position.description,
                "unit": position.unit,
                "similarity": result["similarity"],
                "technical_status": check["status"],
                "blockers": check["blockers"],
                "review_flags": check["review_flags"],
                "source_version_id": digest,
                "source_page": position.pdf_page,
                "source_price": str(position.price) if position.price_verified else None,
                "source_price_verified": position.price_verified,
                "analysis_inputs": position.ingredients if position.price_verified else (),
                "scope_excerpt": position.scope,
            })
        scored.sort(key=lambda c: (
            {"compatible": 0, "review": 1, "blocked": 2}[c["technical_status"]],
            -c["similarity"], c["code"],
        ))
        question = (
            ceramic_question(current.raw_description, scored)
            if family(current.raw_description) == "seramik" else None
        )
        rows.append({
            "clarification": question,
            "work_item_id": current.id, "source_row": current.source_row,
            "revision_id": current.revision_id, "suggestions": scored,
            "saved_selection": (
                _selected_view(
                    saved[str(current.id)],
                    current_revision=current.revision_id,
                    current_pdf_sha=digest,
                    technically_blocked=_saved_choice_blocked(
                        current, saved[str(current.id)], by_code,
                    ),
                ) if str(current.id) in saved else None
            ),
            "related_excel_rows": partners,
            "rejected_candidate_count": rejected,
            "review_summary": (
                issue_summary(current.raw_description, scored, partners)
                if partners else
                "Teknik olarak uyumsuz adaylar elendi; doğrulanabilir poz bulunamadı."
                if not scored and rejected else
                issue_summary(current.raw_description, scored, partners)
            ),
        })
    top_codes = Counter(
        row["suggestions"][0]["code"]
        for row in rows if row["suggestions"]
        and row["suggestions"][0]["technical_status"] != "blocked"
    )
    for row in rows:
        for candidate in row["suggestions"]:
            candidate["possible_shared_scope"] = top_codes[candidate["code"]] > 1
    response.headers.update(NO_STORE)
    return {
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "import_source": _source_view(batch),
        "catalog": {
            "version_id": digest, "synthetic": False, "sha256": digest,
            "institution": "CSB (kullanıcı PDF kaynağı)", "year": 2026,
        },
        "rows": rows, "page_offset": offset,
    }
