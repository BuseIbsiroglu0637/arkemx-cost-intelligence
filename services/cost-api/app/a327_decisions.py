"""Evidence-bound human handoff notes. This endpoint cannot grant approval.

Until a verified engineer role and separate authorization workflow exist, actions
may ONLY request information, reject a recorded candidate, or submit a complete
evidence packet for engineering review. None becomes a cost eligibility decision.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a327_decision_store import EngineerHandoffDecision as Handoff
from .a327_engineer_handoff import (
    _row_status, _file_path, _read_file, _scan, read_analysis_pdf,
)
from .database import get_db
from .models import PdfCandidateSelection, User, WorkItem
from .revisions import effective_item
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a327/imports/{import_id}",
    tags=["A3.27 Review Decisions (pre-approval)"],
)


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["request_information", "reject_candidate", "submit_for_engineering_review"]
    reason: str = Field(default="", max_length=1000)
    expected_source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_previous_id: UUID | None
    request_key: UUID
    confirmation: Literal["I_REVIEWED_SOURCE_EVIDENCE"]

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        return value.strip()


def _latest(db: Session, project_id: str, work_item_id: str):
    return db.scalar(
        select(Handoff).where(
            Handoff.project_id == project_id, Handoff.work_item_id == work_item_id,
        ).order_by(Handoff.created_at.desc(), Handoff.id.desc()).limit(1)
    )


def _serialize(event: Handoff) -> dict:
    return {
        "id": event.id, "work_item_id": event.work_item_id,
        "candidate_code": event.candidate_code, "revision_id": event.revision_id,
        "document_sha256": event.document_sha256,
        "source_fingerprint": event.source_fingerprint,
        "status_at_decision": event.status_at_decision,
        "action": event.action, "reason": event.reason,
        "created_by_id": event.created_by_id, "created_at": event.created_at,
        "previous_id": None if event.previous_key == "initial" else event.previous_key,
        "engineering_approved": False, "approval_allowed": False,
        "cost_allowed": False,
    }


def _evidence_fingerprint(batch, item, current, selection, catalog, document_sha, row):
    """Fingerprint the exact current evidence; reused by list and item review.

    Keep this snapshot format stable: existing decision fingerprints are persisted.
    """
    snapshot = {
        "project_id": batch.project_id, "import_id": batch.id,
        "import_sha256": batch.sha256, "work_item_id": item.id,
        "source_row": item.source_row, "revision_id": current.revision_id,
        "description": current.raw_description,
        "quantity": str(current.quantity), "unit": current.normalized_unit,
        "input_review_required": current.review_required,
        "status": row["status"], "checks": row["checks"],
        "document_sha256": document_sha,
        "candidate_id": selection.position_code if selection else None,
        "candidate_pdf_sha256": selection.pdf_sha256 if selection else None,
        "catalog_pdf_sha256": catalog[0] if catalog else None,
        "saved_candidate": row["saved_candidate"],
        "evidence_page": row["evidence_page"],
    }
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _current(db: Session, user: User, project_id: UUID, import_id: UUID, item_id: UUID):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(item_id), WorkItem.import_id == batch.id,
    ).with_for_update())
    if item is None:
        raise HTTPException(404, "Metraj row not found", headers=NO_STORE)
    current = effective_item(db, item)
    selection = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.work_item_id == item.id,
    ))
    document = _read_file(_file_path(user, project_id))
    blocks, document_sha, document_state = [], None, "missing"
    if document:
        raw, document_sha = document
        try:
            blocks, _ = _scan(raw)
            document_state = "available" if blocks else "unreadable"
        except ValueError:
            document_state = "unreadable"
    catalog = read_analysis_pdf(user) if selection and document_state == "available" else None
    row = _row_status(
        current, item, blocks, document_state, selection, catalog, document_sha,
    )
    fingerprint = _evidence_fingerprint(batch, item, current, selection, catalog, document_sha, row)
    return row, fingerprint


@router.get("/items/{work_item_id}/decision-state")
def decision_state(
    project_id: UUID, import_id: UUID, work_item_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint = _current(db, user, project_id, import_id, work_item_id)
    events = db.scalars(select(Handoff).where(
        Handoff.organization_id == user.organization_id,
        Handoff.project_id == str(project_id),
        Handoff.import_id == str(import_id),
        Handoff.work_item_id == str(work_item_id),
    ).order_by(Handoff.created_at.desc(), Handoff.id.desc()).limit(20)).all()
    previous = events[0] if events else None
    response.headers.update(NO_STORE)
    return {
        "read_only": True, "approval_allowed": False,
        "engineering_approved": False, "cost_allowed": False,
        "work_item_id": str(work_item_id), "status": row["status"],
        "saved_candidate": row["saved_candidate"],
        "source_fingerprint": fingerprint,
        "latest_id": previous.id if previous else None,
        "latest_event": _serialize(previous) if previous else None,
        "events": [{**_serialize(event),
                    "source_current": event.source_fingerprint == fingerprint}
                   for event in events],
        "allowed_actions": [
            "request_information",
            *(
                ["reject_candidate"] if row["saved_candidate"] else []
            ),
            *(
                ["submit_for_engineering_review"]
                if row["status"] == "documented_for_review" else []
            ),
        ],
    }


@router.post("/items/{work_item_id}/decisions", status_code=201)
def record_decision(
    project_id: UUID, import_id: UUID, work_item_id: UUID,
    payload: HandoffRequest, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint = _current(db, user, project_id, import_id, work_item_id)
    request_hash = hashlib.sha256(json.dumps({
        **payload.model_dump(mode="json"),
        "project_id": str(project_id), "import_id": str(import_id),
        "work_item_id": str(work_item_id), "actor_id": user.id,
    }, sort_keys=True).encode()).hexdigest()
    same_request = select(Handoff).where(
        Handoff.organization_id == user.organization_id,
        Handoff.project_id == str(project_id),
        Handoff.request_key == str(payload.request_key),
    )
    previous_attempt = db.scalar(same_request)
    if previous_attempt:
        if previous_attempt.request_sha256 != request_hash:
            raise HTTPException(409, "Request key already used for a different decision")
        response.status_code = 200
        response.headers.update(NO_STORE)
        return _serialize(previous_attempt)

    if fingerprint != payload.expected_source_fingerprint:
        raise HTTPException(409, "Project evidence changed; reopen the decision panel")
    if payload.action == "submit_for_engineering_review" and row["status"] != "documented_for_review":
        raise HTTPException(409, "Cannot submit a row without complete comparable evidence")
    if payload.action == "reject_candidate" and not row["saved_candidate"]:
        raise HTTPException(409, "No verified saved position to reject")

    previous = _latest(db, str(project_id), str(work_item_id))
    expected = str(payload.expected_previous_id) if payload.expected_previous_id else None
    if expected != (previous.id if previous else None):
        raise HTTPException(409, "Review history changed; reload the decision panel")

    event = Handoff(
        organization_id=user.organization_id,
        project_id=str(project_id), import_id=str(import_id),
        work_item_id=str(work_item_id), candidate_code=row["saved_candidate"],
        revision_id=row["revision_id"], document_sha256=row["document_sha256"],
        source_fingerprint=fingerprint, status_at_decision=row["status"],
        action=payload.action, reason=payload.reason or "Gerekçe belirtilmedi",
        created_by_id=user.id, previous_key=expected or "initial",
        request_key=str(payload.request_key), request_sha256=request_hash,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        attempt = db.scalar(same_request)
        if attempt is None or attempt.request_sha256 != request_hash:
            raise HTTPException(409, "Concurrent review decision; reload") from None
        event = attempt
        response.status_code = 200
    response.headers.update(NO_STORE)
    return _serialize(event)
