"""A3.18: user-authorized, local-only direct PDF source for automatic matching.

The actual PDF remains in the organization's local upload area, outside Git.
No synthetic catalog fallback, no engineering approval, no cost postings.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source, _source_view
from .a318_pdf_engine import PdfPosition, read_positions, verified_price_audit
from .a324_ceramic_features import ceramic_finish_conflict, ceramic_question
from .a343_work_scope import scope_blocker
from .a325_review_queue import classify_row
from .a335_plaster_matching import plaster_stages
from .a320_smart_matching import (
    enrich_technical,
    find_pdf_candidates,
    issue_summary,
    potential_plaster_pairs,
)
from .database import get_db
from .m2 import tenant_project
from .matching import family
from .models import ImportBatch, PdfCandidateSelection, ManualPositionRequest, User, WorkItem, now_utc
from .revisions import effective_item
from .security import current_user
from sqlalchemy.exc import IntegrityError
from .technical import compare

router = APIRouter(prefix="/api/projects/{project_id}/a318", tags=["A3.18 Local PDF Analysis"])
PDF_LIMIT = 16 * 1024 * 1024
MAX_ROWS = 20


class SavePdfCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_code: str = Field(pattern=r"^15\.\d{3}\.\d{4}$")
    expected_revision_id: UUID | None
    expected_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SaveManualPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A manually entered code is not a verified PDF poz until an exact lookup.
    position_code: str = Field(min_length=4, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9./_-]{3,79}$")
    expected_revision_id: UUID | None


def _manual_view(entry: ManualPositionRequest | None, current, found) -> dict | None:
    if entry is None:
        return None
    is_current = entry.revision_id == current.revision_id
    digest, positions = found if found else (None, ())
    position = next((p for p in positions if p.id == entry.position_code), None)
    check = _pdf_candidate_check(current, position) if position else None
    allowed = bool(is_current and position and check and check["status"] != "blocked")
    match = ({
        "code": position.id,
        "description": position.description,
        "unit": position.unit,
        "similarity": 0.0,
        "technical_status": check["status"],
        "blockers": check["blockers"],
        "review_flags": check["review_flags"],
        "source_version_id": digest,
        "possible_shared_scope": False,
        "source_page": position.pdf_page,
        "source_price": str(position.price) if position.price_verified else None,
        "source_price_verified": position.price_verified,
        "analysis_inputs": position.ingredients if position.price_verified else (),
        "scope_excerpt": position.scope,
        "pdf_edition_date": "1.01.2026",
        "price_audit": verified_price_audit(position),
    } if is_current and position else None)
    return {
        "position_code": entry.position_code,
        "current": is_current,
        "pdf_found": bool(position),
        "can_select": allowed,
        "technical_status": check["status"] if check else None,
        "pdf_match": match,
        "cost_allowed": False,
        "engineering_approved": False,
    }


@router.post("/imports/{import_id}/items/{work_item_id}/manual-position", status_code=200)
def save_manual_position(
    project_id: UUID, import_id: UUID, work_item_id: UUID,
    payload: SaveManualPositionRequest, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(work_item_id), WorkItem.import_id == batch.id,
    ))
    if item is None:
        raise HTTPException(404, "Metraj row not found", headers=NO_STORE)
    current = effective_item(db, item)
    if current.revision_id != (str(payload.expected_revision_id) if payload.expected_revision_id else None):
        raise HTTPException(409, "Metraj revision changed; reload before saving", headers=NO_STORE)
    entry = db.scalar(select(ManualPositionRequest).where(
        ManualPositionRequest.organization_id == user.organization_id,
        ManualPositionRequest.project_id == batch.project_id,
        ManualPositionRequest.import_id == batch.id,
        ManualPositionRequest.work_item_id == item.id,
    ).with_for_update())
    if entry is None:
        entry = ManualPositionRequest(
            organization_id=user.organization_id,
            project_id=batch.project_id, import_id=batch.id, work_item_id=item.id,
        )
        db.add(entry)
    entry.revision_id = current.revision_id
    entry.position_code = payload.position_code.strip().upper()
    entry.recorded_by_id = user.id
    entry.updated_at = now_utc()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent manual poz edit; refresh", headers=NO_STORE) from None
    response.headers.update(NO_STORE)
    return {
        "saved": True, "manual_position": _manual_view(entry, current, _read(user)),
        "cost_allowed": False, "engineering_approved": False,
    }


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
        position_scope=position.scope,
        position_code=position.id,
    )
    scope_issue = scope_blocker(current.raw_description, position.description)
    if scope_issue:
        check = {
            **check, "blockers": sorted(set(check["blockers"]) | {scope_issue}),
            "status": "blocked", "manual_approval_allowed": False,
        }
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


def _suggestions_result(
    project_id: UUID, import_id: UUID, response: Response,
    user: User, db: Session, offset: int, limit: int,
):
    """One matching pipeline for a 20-row page and a full-import review summary."""
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
        PdfCandidateSelection.work_item_id.in_([item.id for item in effective[offset:offset + limit]]),
    )).all()
    saved = {row.work_item_id: row for row in saved_rows}
    visible_ids = [item.id for item in effective[offset:offset + limit]]
    manual_rows = db.scalars(select(ManualPositionRequest).where(
        ManualPositionRequest.organization_id == user.organization_id,
        ManualPositionRequest.project_id == batch.project_id,
        ManualPositionRequest.import_id == batch.id,
        ManualPositionRequest.work_item_id.in_(visible_ids),
    )).all()
    manual_by_id = {row.work_item_id: row for row in manual_rows}
    rows = []
    for current in effective[offset:offset + limit]:
        partners = partner_rows.get(str(current.id), [])
        candidates = find_pdf_candidates(current, positions)
        scored = []
        excluded = []
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
                if len(excluded) < 3:
                    excluded.append({
                        "code": position.id,
                        "description": position.description,
                        "source_page": position.pdf_page,
                        "reason": (
                            check["blockers"][0] if check["blockers"]
                            else "MATERIAL_FINISH_CONFLICT"
                        ),
                        "cost_allowed": False,
                        "selectable": False,
                    })
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
                # This date is verified by read_positions against page 6 of
                # the specific PDF edition, not the live/current official rate.
                "pdf_edition_date": "1.01.2026",
                "price_audit": verified_price_audit(position),
                "scope_excerpt": position.scope,
            })
        expected_plaster_stage = plaster_stages(current.raw_description)
        scored.sort(key=lambda c: (
            {"compatible": 0, "review": 1, "blocked": 2}[c["technical_status"]],
            # Do not undo A3.35's safe same-layer retrieval with a raw
            # lexical re-sort; a generic plaster can share many words.
            int(bool(expected_plaster_stage) and
                plaster_stages(c["description"]) != expected_plaster_stage),
            -c["similarity"], c["code"],
        ))
        question = (
            ceramic_question(current.raw_description, scored)
            if family(current.raw_description) == "seramik" else None
        )
        rows.append({
            "clarification": question,
            "work_item_id": current.id, "source_row": current.source_row,
            "description": current.raw_description,
            "quantity": str(current.quantity) if current.quantity is not None else None,
            "unit": current.normalized_unit,
            "revision_id": current.revision_id, "suggestions": scored,
            "excluded_positions": excluded,
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
            "manual_position": _manual_view(manual_by_id.get(current.id), current, found),
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
    by_item = {str(item.id): item for item in effective[offset:offset + limit]}
    for row in rows:
        for candidate in row["suggestions"]:
            candidate["possible_shared_scope"] = top_codes[candidate["code"]] > 1
        current = by_item[str(row["work_item_id"])]
        row["triage"] = classify_row(
            description=current.raw_description,
            candidates=row["suggestions"],
            saved_selection=row["saved_selection"],
            clarification=row["clarification"],
            related_excel_rows=row["related_excel_rows"],
            quantity_known=current.quantity is not None,
            unit_known=current.normalized_unit is not None,
            input_review_required=current.review_required,
        )
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


MAX_FULL_REVIEW_ROWS = 2000


@router.get("/imports/{import_id}/suggestions")
def suggestions_from_pdf(
    project_id: UUID,
    import_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return _suggestions_result(project_id, import_id, response, user, db, offset, MAX_ROWS)


@router.get("/imports/{import_id}/review-coverage")
def full_import_review_coverage(
    project_id: UUID, import_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """On-demand, source-bound, read-only overview of every imported metraj row.

    This is a *matching review* overview, never a cost-eligibility decision.
    A PDF candidate or even 'prechecked' status does not create an M5 estimate.
    """
    batch = _source(db, user, str(project_id), str(import_id))
    total = db.scalar(select(func.count()).select_from(WorkItem).where(
        WorkItem.import_id == batch.id,
    )) or 0
    if total > MAX_FULL_REVIEW_ROWS:
        raise HTTPException(422, "Import exceeds the full-review limit; use paged review")
    result = _suggestions_result(project_id, import_id, response, user, db, 0, MAX_FULL_REVIEW_ROWS)
    counters = Counter()
    causes = Counter()
    items = []
    for row in result["rows"]:
        options = row["suggestions"]
        triage = row["triage"]
        group = triage["group"]
        if not options:
            state = "no_match"
        elif group == "needs_info":
            state = "needs_info"
        elif group == "prechecked":
            state = "rule_prechecked"
        else:
            state = "needs_review"
        counters[state] += 1
        if row["manual_position"] and row["manual_position"].get("current"):
            counters["manual_codes"] += 1
        if row["excluded_positions"]:
            counters["rows_with_exclusions"] += 1
        cause = triage["reason"] if options else (
            "Teknik uyumsuz pozlar elendi" if row["rejected_candidate_count"]
            else "Kaynak PDF'de uygun poz bulunamadı"
        )
        causes[cause] += 1
        items.append({
            "work_item_id": row["work_item_id"],
            "source_row": row["source_row"],
            "description": row["description"],
            "quantity": row["quantity"], "unit": row["unit"],
            "state": state,
            "reason": cause,
            "suggested_code": options[0]["code"] if options else None,
            "candidate_count": len(options),
            "manual_code": (
                row["manual_position"]["position_code"]
                if row["manual_position"] else None
            ),
            "cost_allowed": False,
            "engineering_approved": False,
        })
    response.headers.update(NO_STORE)
    return {
        "schema": "arkemx.a344.review_coverage.v1",
        "read_only": True,
        "approval_allowed": False,
        "cost_allowed": False,
        "source_sha256": result["catalog"]["sha256"],
        "import_id": str(import_id),
        "import_sha256": result["import_source"]["sha256"],
        "total_rows": total,
        "scanned_rows": len(items),
        "complete": len(items) == total,
        "counts": {
            "no_match": counters["no_match"],
            "needs_info": counters["needs_info"],
            "needs_review": counters["needs_review"],
            "rule_prechecked": counters["rule_prechecked"],
            "manual_codes": counters["manual_codes"],
            "rows_with_exclusions": counters["rows_with_exclusions"],
        },
        "top_reasons": [
            {"reason": reason, "count": count}
            for reason, count in causes.most_common(8)
        ],
        "rows": items,
        "cost_note": (
            "PDF poz taraması mühendis onayı veya M5 maliyet yetkisi vermez. "
            "Yalnızca ayrıca onaylanmış fiyatlandırılabilir kalemler M5'e alınır."
        ),
    }
