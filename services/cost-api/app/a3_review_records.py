"""Explicitly saved, immutable technical previews with currentness checks."""
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .a3_batch_review import (
    NO_STORE,
    BatchReviewRequest,
    _error,
    preview_batch_review,
)
from .a3_review_store import TechnicalReviewRecord
from .database import get_db
from .models import (
    ImportBatch,
    MetrajImportExclusion,
    Project,
    User,
    WorkItem,
    ident,
    now_utc,
)
from .revisions import effective_item
from .security import current_user
from .technical_analysis.owned_synthetic_source import (
    CODE,
    fixture_identity,
    fixture_sha256,
)

router = APIRouter(prefix="/api/projects/{project_id}/a3", tags=["A3 Saved Reviews"])


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def engine_digest() -> str:
    base = Path(__file__).parent / "technical_analysis"
    names = ("layers.py", "comparator.py", "critical_attributes.py", "layer_dosage.py",
             "batch_technical_review.py", "support_registry.py", "pdf_analysis_source.py", "owned_synthetic_source.py")
    h = hashlib.sha256(b"arkemx.saved_review.v1")
    for name in names:
        h.update(name.encode())
        h.update((base / name).read_bytes())
    return h.hexdigest()


class SaveReviewRequest(BatchReviewRequest):
    title: str = Field(min_length=3, max_length=120)
    request_key: UUID
    expected_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("A meaningful title is required")
        return value.strip()


def project_access(db: Session, user: User, project_id: str) -> None:
    if db.scalar(select(Project.id).where(Project.id == project_id,
                                         Project.organization_id == user.organization_id)) is None:
        raise _error(404, "Project or review not found")


def owned_record(db: Session, user: User, project_id: str, record_id: str) -> TechnicalReviewRecord:
    project_access(db, user, project_id)
    row = db.scalar(select(TechnicalReviewRecord).where(
        TechnicalReviewRecord.id == record_id, TechnicalReviewRecord.project_id == project_id,
        TechnicalReviewRecord.organization_id == user.organization_id))
    if row is None:
        raise _error(404, "Project or review not found")
    return row


def decode(row: TechnicalReviewRecord) -> dict:
    try:
        data = json.loads(row.snapshot_json)
        if (digest(data) != row.snapshot_sha256 or data["id"] != row.id
                or data["project_id"] != row.project_id or data["import_id"] != row.import_id
                or data["organization_id"] != row.organization_id or data["title"] != row.title
                or data["created_by_id"] != row.created_by_id
                or len(data["report"]["rows"]) != row.row_count
                or data["report"]["import_source"]["import_id"] != row.import_id
                or data["report"]["import_source"]["project_id"] != row.project_id
                or data["report"]["approval_allowed"] is not False
                or data["report"]["read_only"] is not True
                or any(item["approval_allowed"] is not False for item in data["report"]["rows"])):
            raise ValueError("Invalid snapshot")
        return data
    except (ValueError, KeyError, TypeError) as exc:
        raise _error(409, "Saved review integrity check failed") from exc


def view(row: TechnicalReviewRecord, db: Session) -> dict:
    saved = decode(row)
    report = saved["report"]
    changed, unknown = [], []
    batch = db.get(ImportBatch, row.import_id)
    available = bool(batch and batch.project_id == row.project_id)
    if not available:
        changed.append("IMPORT_NOT_AVAILABLE")
    elif batch.sha256 != report["import_source"]["sha256"]:
        changed.append("IMPORT_CHANGED")
    if db.get(MetrajImportExclusion, row.import_id):
        changed.append("IMPORT_EXCLUDED")
        available = False
    fresh_rows = []
    for item in report["rows"]:
        identity = item["identity"]
        source = db.get(WorkItem, identity["work_item_id"])
        if source is None or source.import_id != row.import_id:
            changed.append("ROW_NOT_AVAILABLE")
            available = False
            continue
        current = effective_item(db, source)
        if (identity["revision_id"] != current.revision_id
                or identity["source_row"] != current.source_row
                or item["effective_description"] != current.raw_description
                or item["quantity"] != (str(current.quantity) if current.quantity is not None else None)
                or item["unit"] != current.normalized_unit):
            changed.append("METRAJ_CHANGED")
        fresh_rows.append({"work_item_id": source.id, "source_row": source.source_row,
                           "original_description": source.raw_description,
                           "effective_description": current.raw_description,
                           "quantity": str(current.quantity) if current.quantity is not None else None,
                           "unit": current.normalized_unit, "revision_id": current.revision_id,
                           "input_review_required": current.review_required})
    try:
        if engine_digest() != saved["engine_sha256"]:
            changed.append("ENGINE_CHANGED")
    except OSError:
        unknown.append("ENGINE_UNVERIFIED")
    real_rows = []
    for item in report["rows"]:
        if item["candidate_code"] == CODE:
            technical = item.get("technical_source") or {}
            current = fixture_identity()
            if (technical.get("kind") != "synthetic_owned" or technical.get("sha256") != fixture_sha256()
                    or technical.get("description") != current["description"] or technical.get("unit") != current["unit"]):
                changed.append("SYNTHETIC_SOURCE_CHANGED")
        else:
            real_rows.append(item)
    hashes = {item["source_price"]["source"]["sha256"] for item in real_rows if item["source_price"]}
    if real_rows and len(hashes) == 1:
        try:
            h = hashlib.sha256()
            with Path(os.environ.get("ARKEMX_ANALYSIS_PDF", "")).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() not in hashes:
                changed.append("PDF_CHANGED")
        except (OSError, ValueError):
            unknown.append("PDF_UNVERIFIED")
    elif real_rows:
        unknown.append("PDF_UNVERIFIED")
    return {
        "schema": "arkemx.saved_review.v1", "read_only": True, "approval_allowed": False,
        "record": {"id": row.id, "title": saved["title"], "created_at": saved["created_at"],
                   "snapshot_sha256": row.snapshot_sha256, "row_count": row.row_count},
        "report": report,
        "currentness": {"status": "changed" if changed else "unverified" if unknown else "unchanged",
                        "flags": sorted(set(changed + unknown)), "engineering_approval": False},
        "resume_allowed": available and len(fresh_rows) == row.row_count,
        "resume_rows": fresh_rows if available else [],
    }


@router.post("/imports/{import_id}/reviews", status_code=201)
def save_review(project_id: UUID, import_id: UUID, payload: SaveReviewRequest, response: Response,
                user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    pid, iid = str(project_id), str(import_id)
    project_access(db, user, pid)
    request_hash = digest({**payload.model_dump(mode="json"), "import_id": iid})
    existing = db.scalar(select(TechnicalReviewRecord).where(
        TechnicalReviewRecord.organization_id == user.organization_id,
        TechnicalReviewRecord.project_id == pid, TechnicalReviewRecord.request_key == str(payload.request_key)))
    if existing:
        if existing.request_sha256 != request_hash:
            raise _error(409, "Request key already used for different content")
        response.headers.update(NO_STORE)
        response.status_code = 200
        return view(existing, db)
    report = preview_batch_review(project_id, import_id, BatchReviewRequest(rows=payload.rows),
                                  Response(), user, db)
    if digest(report) != payload.expected_report_sha256:
        raise _error(409, "Preview changed; run technical review again before saving")
    snapshot = {"id": ident(), "project_id": pid, "import_id": iid,
                "organization_id": user.organization_id, "created_by_id": user.id,
                "title": payload.title, "created_at": now_utc().isoformat(),
                "engine_sha256": engine_digest(), "report": report}
    row = TechnicalReviewRecord(id=snapshot["id"], organization_id=user.organization_id,
        project_id=pid, import_id=iid, created_by_id=user.id, title=payload.title,
        row_count=len(payload.rows), request_key=str(payload.request_key), request_sha256=request_hash,
        snapshot_json=canonical(snapshot), snapshot_sha256=digest(snapshot))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(TechnicalReviewRecord).where(
            TechnicalReviewRecord.organization_id == user.organization_id,
            TechnicalReviewRecord.project_id == pid,
            TechnicalReviewRecord.request_key == str(payload.request_key)))
        if existing is None or existing.request_sha256 != request_hash:
            raise _error(409, "Review save conflicted; reload saved reviews") from None
        response.status_code = 200
        row = existing
    response.headers.update(NO_STORE)
    return view(row, db)


@router.get("/imports/{import_id}/reviews")
def list_reviews(project_id: UUID, import_id: UUID, response: Response,
                 user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
                 offset: Annotated[int, Query(ge=0)] = 0):
    project_access(db, user, str(project_id))
    batch = db.get(ImportBatch, str(import_id))
    if batch is None or batch.project_id != str(project_id):
        raise _error(404, "Project or import not found")
    rows = db.execute(select(TechnicalReviewRecord.id, TechnicalReviewRecord.title,
        TechnicalReviewRecord.created_at, TechnicalReviewRecord.row_count).where(
            TechnicalReviewRecord.project_id == str(project_id),
            TechnicalReviewRecord.organization_id == user.organization_id,
            TechnicalReviewRecord.import_id == str(import_id)).order_by(
                TechnicalReviewRecord.created_at.desc(), TechnicalReviewRecord.id.desc())
                .offset(offset).limit(21)).all()
    response.headers.update(NO_STORE)
    return {"read_only": True, "approval_allowed": False,
            "records": [dict(row._mapping) for row in rows[:20]],
            "next_offset": offset + 20 if len(rows) > 20 else None}


@router.get("/reviews/{record_id}")
def read_review(project_id: UUID, record_id: UUID, response: Response,
                user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    row = owned_record(db, user, str(project_id), str(record_id))
    response.headers.update(NO_STORE)
    return view(row, db)
