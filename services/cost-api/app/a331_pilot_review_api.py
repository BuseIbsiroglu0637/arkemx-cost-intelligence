"""Pilot technical review: authenticated user acceptance, NOT engineer signoff.

Source/current revision fingerprint and explicit attestation are required.
This API intentionally never grants M5 cost eligibility or engineering credentials.
"""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE
from .a330_editable_analysis import _fingerprint_request, _latest_revision, _source
from .a331_pilot_review_store import PilotTechnicalReviewEvent
from .database import get_db
from .models import User
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a331/imports/{import_id}/items/{work_item_id}",
    tags=["A3.31 Pilot Technical Review (not engineering signoff)"],
)


class PilotDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "reopen"]
    reason: str = Field(default="", max_length=1000)
    expected_source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_analysis_revision_id: UUID
    expected_previous_event_id: UUID | None
    request_key: UUID
    acknowledgement: Literal["I_REVIEWED_SOURCE_AND_THIS_IS_NOT_ENGINEER_SIGNOFF"]

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


def _latest(db: Session, work_item_id: str):
    return db.scalar(select(PilotTechnicalReviewEvent).where(
        PilotTechnicalReviewEvent.work_item_id == work_item_id,
    ).order_by(PilotTechnicalReviewEvent.sequence.desc()).limit(1))


def _state(fingerprint: str, revision, event, evidence_ready: bool) -> dict:
    is_current = bool(
        revision is not None and revision.source_fingerprint == fingerprint
        and event is not None and event.source_fingerprint == fingerprint
        and event.analysis_revision_id == revision.id
    )
    return {
        "source_fingerprint": fingerprint,
        "analysis_revision_id": revision.id if revision else None,
        "evidence_ready": evidence_ready,
        "pilot_confirmed": bool(is_current and evidence_ready and event.action == "accept"),
        "engineering_approved": False,  # Pilot acceptance never asserts a professional signoff.
        "cost_allowed": False,
        "last_event": ({
            "id": event.id, "action": event.action, "reason": event.reason,
            "recorded_by_id": event.recorded_by_id,
            "created_at": event.created_at,
            "source_current": is_current,
        } if event else None),
    }


@router.get("/pilot/state")
def pilot_review_state(
    project_id: UUID, import_id: UUID, work_item_id: UUID,
    response: Response, user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint, position, digest = _source(
        db, user, project_id, import_id, work_item_id,
    )
    revision = _latest_revision(db, str(work_item_id))
    event = _latest(db, str(work_item_id))
    response.headers.update(NO_STORE)
    return _state(fingerprint, revision, event, row["status"] == "documented_for_review")


@router.post("/pilot/decisions", status_code=201)
def record_pilot_review(
    project_id: UUID, import_id: UUID, work_item_id: UUID,
    payload: PilotDecisionRequest, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint, position, digest = _source(
        db, user, project_id, import_id, work_item_id,
    )
    request_hash = _fingerprint_request(payload, user, project_id, work_item_id)
    existing = db.scalar(select(PilotTechnicalReviewEvent).where(
        PilotTechnicalReviewEvent.organization_id == user.organization_id,
        PilotTechnicalReviewEvent.project_id == str(project_id),
        PilotTechnicalReviewEvent.request_key == str(payload.request_key),
    ))
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Request key already used")
        response.status_code = 200
        response.headers.update(NO_STORE)
        return {
            "id": existing.id, "action": existing.action,
            "engineering_approved": False, "cost_allowed": False,
        }

    revision = _latest_revision(db, str(work_item_id))
    if (
        fingerprint != payload.expected_source_fingerprint
        or not revision
        or revision.id != str(payload.expected_analysis_revision_id)
        or revision.source_fingerprint != fingerprint
    ):
        raise HTTPException(409, "Analysis or evidence changed. Reload before confirming.")
    latest = _latest(db, str(work_item_id))
    expected = str(payload.expected_previous_event_id) if payload.expected_previous_event_id else None
    if expected != (latest.id if latest else None):
        raise HTTPException(409, "Pilot review history changed. Reload.")
    current = _state(fingerprint, revision, latest, row["status"] == "documented_for_review")
    if payload.action == "accept":
        if not current["evidence_ready"]:
            raise HTTPException(409, "Project specification and position are not yet compatible")
        if current["pilot_confirmed"]:
            raise HTTPException(409, "Already accepted; choose reopen to revise")
    elif not current["pilot_confirmed"]:
        raise HTTPException(409, "No current pilot acceptance to reopen")

    event = PilotTechnicalReviewEvent(
        organization_id=user.organization_id, project_id=str(project_id),
        import_id=str(import_id), work_item_id=str(work_item_id),
        sequence=latest.sequence + 1 if latest else 1,
        analysis_revision_id=revision.id, source_fingerprint=fingerprint,
        action=payload.action, reason=payload.reason or "Gerekçe belirtilmedi",
        recorded_by_id=user.id,
        request_key=str(payload.request_key), request_hash=request_hash,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent review decision; reload") from None
    response.headers.update(NO_STORE)
    return {
        "id": event.id, "action": event.action,
        "pilot_confirmed": event.action == "accept",
        "engineering_approved": False, "cost_allowed": False,
    }
