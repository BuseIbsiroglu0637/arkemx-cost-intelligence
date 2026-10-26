"""M5.2.1 safety controls. No delete, no implicit prior-approval transfer.

Queue cancel is a SQLite-compatible compare-and-swap against *queued*, lease-free
jobs. A worker that acquired the lease first wins; no unsafe running cancellation.
Import exclusion is an append-only-looking, irreversible source annotation in this
pilot. It forbids NEW matching from a bad latest file rather than quietly
reactivating an older M4.2 decision.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .database import get_db
from .security import current_user
from .m2 import tenant_project
from .models import (
    BulkJob, ImportBatch, MetrajImportExclusion, M43QueueControlEvent, User
)

router = APIRouter(prefix="/api/projects/{project_id}/m521", tags=["M5.2.1 Safe Revision & Queue"])


class OperatorReason(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


def _admin(user):
    if user.role != "admin":
        raise HTTPException(403, "Only project organization administrators may change job/source status")


def _reason(text):
    clean = text.strip()
    if len(clean) < 10:
        raise HTTPException(422, "Reason must contain at least 10 non-space characters")
    return clean


def _job(db, user, project_id, job_id):
    job = db.scalar(select(BulkJob).where(
        BulkJob.id == job_id, BulkJob.project_id == project_id,
        BulkJob.organization_id == user.organization_id))
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _import(db, user, project_id, import_id):
    batch = db.scalar(select(ImportBatch).where(
        ImportBatch.id == import_id, ImportBatch.project_id == project_id))
    if batch is None:
        raise HTTPException(404, "Metraj import not found")
    return batch


@router.get("/jobs")
def jobs(project_id: str, user: User = Depends(current_user),
         db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    queued = db.scalars(select(BulkJob).where(
        BulkJob.project_id == project_id,
        BulkJob.organization_id == user.organization_id
    ).order_by(BulkJob.created_at.desc(), BulkJob.id.desc()).limit(50)).all()
    events = {event.job_id: event for event in db.scalars(
        select(M43QueueControlEvent).where(
            M43QueueControlEvent.project_id == project_id,
            M43QueueControlEvent.organization_id == user.organization_id)).all()}
    return [{
        "id": job.id, "import_id": job.import_id, "status": job.status,
        "processed_rows": job.processed_rows, "total_rows": job.total_rows,
        "lease_owner_active": bool(job.lease_owner),
        "failure_reason": job.failure_reason,
        "cancelled_by_operator": job.id in events,
        "cancel_reason": events[job.id].reason if job.id in events else None,
    } for job in queued]


@router.post("/jobs/{job_id}/cancel")
def cancel_pending(project_id: str, job_id: str, payload: OperatorReason,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    _admin(user)
    reason = _reason(payload.reason)
    job = _job(db, user, project_id, job_id)
    previous = db.scalar(select(M43QueueControlEvent).where(
        M43QueueControlEvent.job_id == job.id))
    if previous:
        return {"id": job.id, "status": job.status, "cancelled": True,
                "reason": previous.reason, "idempotent": True}
    if job.status != "queued" or job.lease_owner is not None:
        raise HTTPException(409, "Only a queued job without an active lease can be cancelled")
    source = _import(db, user, project_id, job.import_id)
    # COMPARE AND SWAP: worker lease claim and this update cannot both win.
    changed = db.execute(update(BulkJob).where(
        BulkJob.id == job.id, BulkJob.project_id == project_id,
        BulkJob.organization_id == user.organization_id,
        BulkJob.status == "queued", BulkJob.lease_owner.is_(None)
    ).values(status="blocked", failure_reason="Cancelled by operator: " + reason[:275],
             lease_owner=None, lease_until=None))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "The worker has started processing; cancellation was not applied")
    db.add(M43QueueControlEvent(
        job_id=job.id, project_id=project_id, organization_id=user.organization_id,
        import_sha256=source.sha256, action="cancel_queued", reason=reason,
        actor_id=user.id))
    db.commit()
    return {"id":job.id, "status":"blocked", "cancelled":True,
            "reason":reason, "idempotent":False,
            "note":"Job and its frozen technical snapshot are retained; no approval is published."}


@router.get("/imports")
def imports(project_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    batches = db.scalars(select(ImportBatch).where(
        ImportBatch.project_id == project_id).order_by(
        ImportBatch.created_at.desc(), ImportBatch.id.desc())).all()
    excluded = {item.import_id: item for item in db.scalars(
        select(MetrajImportExclusion).where(
            MetrajImportExclusion.project_id == project_id,
            MetrajImportExclusion.organization_id == user.organization_id)).all()}
    return [{
        "id": b.id, "filename": b.original_filename, "sha256": b.sha256,
        "created_at": b.created_at, "row_count": b.row_count,
        "is_latest": i == 0, "excluded": b.id in excluded,
        "exclusion_reason": excluded[b.id].reason if b.id in excluded else None,
    } for i, b in enumerate(batches)]


@router.post("/imports/{import_id}/exclude")
def exclude_import(project_id: str, import_id: str, payload: OperatorReason,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    _admin(user)
    reason = _reason(payload.reason)
    batch = _import(db, user, project_id, import_id)
    existing = db.get(MetrajImportExclusion, import_id)
    if existing:
        if existing.project_id != project_id or existing.organization_id != user.organization_id:
            raise HTTPException(404, "Import not found")
        return {"import_id": import_id, "excluded": True,
                "reason": existing.reason, "idempotent": True}
    current = db.scalar(select(BulkJob).where(
        BulkJob.project_id == project_id, BulkJob.import_id == import_id,
        BulkJob.status.in_(("queued", "running"))).limit(1))
    if current:
        raise HTTPException(409, "First cancel queued jobs; running jobs cannot be excluded")
    db.add(MetrajImportExclusion(
        import_id=import_id, project_id=project_id,
        organization_id=user.organization_id, original_sha256=batch.sha256,
        reason=reason, excluded_by_id=user.id))
    db.commit()
    return {"import_id": import_id, "excluded": True, "reason": reason,
            "idempotent": False,
            "note": "This immutable source remains available in history but cannot start NEW analysis. If newest, upload a clean newer source before resuming matching."}
