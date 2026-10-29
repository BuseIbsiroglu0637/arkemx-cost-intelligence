"""Evidence-bound assessments; cannot approve engineering or change costs."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .a3_assessment_store import TechnicalReviewAssessment as Assessment
from .a3_batch_review import NO_STORE, _error
from .a3_review_records import decode, digest, owned_record, view
from .database import get_db
from .models import User
from .security import current_user

router = APIRouter(prefix="/api/projects/{project_id}/a3/reviews/{record_id}",
                   tags=["A3 Review Assessments"])


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_id: UUID
    action: Literal["reject_candidate", "request_information"]
    reason: str = Field(min_length=10, max_length=1000)
    expected_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_previous_id: UUID | None
    request_key: UUID

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Provide a reason of at least 10 characters")
        return value


def statement(record_id: str, item_id: str):
    return select(Assessment).where(Assessment.record_id == record_id,
                                    Assessment.work_item_id == item_id)


def serialize(row: Assessment) -> dict:
    return {"id": row.id, "record_id": row.record_id, "work_item_id": row.work_item_id,
            "candidate_code": row.candidate_code, "revision_id": row.revision_id,
            "snapshot_sha256": row.snapshot_sha256, "action": row.action, "reason": row.reason,
            "created_by_id": row.created_by_id, "created_at": row.created_at,
            "previous_id": None if row.previous_key == "initial" else row.previous_key,
            "approval_allowed": False, "engineering_approval": False}


def source_row(record, item_id):
    saved = decode(record)
    item = next((r for r in saved["report"]["rows"] if r["identity"]["work_item_id"] == item_id), None)
    if item is None:
        raise _error(404, "Row is not part of this review")
    return item


def latest(db, record_id, item_id):
    return db.scalar(statement(record_id, item_id).order_by(
        Assessment.created_at.desc(), Assessment.id.desc()).limit(1))


@router.get("/assessments")
def history(project_id: UUID, record_id: UUID, work_item_id: UUID, response: Response,
            user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
            offset: Annotated[int, Query(ge=0)] = 0):
    record = owned_record(db, user, str(project_id), str(record_id))
    source_row(record, str(work_item_id))
    state = view(record, db)
    rows = db.scalars(statement(record.id, str(work_item_id)).order_by(
        Assessment.created_at.desc(), Assessment.id.desc()).offset(offset).limit(21)).all()
    top = latest(db, record.id, str(work_item_id))
    response.headers.update(NO_STORE)
    return {"record_id": record.id, "work_item_id": str(work_item_id),
            "snapshot_sha256": record.snapshot_sha256, "approval_allowed": False,
            "engineering_approval": False, "currentness": state["currentness"],
            "assessment_allowed": state["currentness"]["status"] == "unchanged",
            "latest_id": top.id if top else None,
            "events": [serialize(row) for row in rows[:20]],
            "next_offset": offset + 20 if len(rows) > 20 else None}


@router.post("/assessments", status_code=201)
def assess(project_id: UUID, record_id: UUID, payload: AssessmentRequest, response: Response,
           user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    record = owned_record(db, user, str(project_id), str(record_id))
    item = source_row(record, str(payload.work_item_id))
    request_hash = digest({**payload.model_dump(mode="json"), "record_id": record.id,
                           "created_by_id": user.id})
    key_query = select(Assessment).where(Assessment.organization_id == user.organization_id,
        Assessment.project_id == str(project_id), Assessment.request_key == str(payload.request_key))
    existing = db.scalar(key_query)
    # A retry returns the original event, even if sources changed after it was saved.
    if existing:
        if existing.request_sha256 != request_hash:
            raise _error(409, "Request key already used for another assessment")
        response.status_code = 200
        response.headers.update(NO_STORE)
        return serialize(existing)
    if payload.expected_snapshot_sha256 != record.snapshot_sha256:
        raise _error(409, "Review evidence changed; reopen the saved review")
    state = view(record, db)
    if state["currentness"]["status"] != "unchanged":
        raise _error(409, "Review is changed or unverified; run and save a new comparison")
    if payload.action == "reject_candidate" and not item["candidate_code"]:
        raise _error(409, "Select and review a candidate before rejecting it")
    previous = latest(db, record.id, str(payload.work_item_id))
    expected = str(payload.expected_previous_id) if payload.expected_previous_id else None
    if expected != (previous.id if previous else None):
        raise _error(409, "Assessment history changed; reload history before submitting")
    event = Assessment(organization_id=user.organization_id, project_id=str(project_id),
        record_id=record.id, work_item_id=str(payload.work_item_id), created_by_id=user.id,
        candidate_code=item["candidate_code"], revision_id=item["identity"]["revision_id"],
        snapshot_sha256=record.snapshot_sha256, action=payload.action, reason=payload.reason,
        previous_key=expected or "initial", request_key=str(payload.request_key), request_sha256=request_hash)
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(key_query)
        if existing is None or existing.request_sha256 != request_hash:
            raise _error(409, "Concurrent assessment; reload history before submitting") from None
        event = existing
        response.status_code = 200
    response.headers.update(NO_STORE)
    return serialize(event)
