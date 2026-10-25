"""M4.3 queued batch REST API. Requests only enqueue/poll; local CLI performs work."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from .models import (
    User, BulkJob, MatchRun, ImportBatch, WorkItem, CatalogVersion,
    CatalogSource, CatalogPosition, CatalogImport,
)
from .m2 import tenant_project, latest_run, DEMO_INSTITUTION, DEMO_SCOPE
from .m3 import eligible_version
from .revisions import effective_item, frozen_snapshot
from .m43_worker import ALGORITHM, ROW_LIMIT, POSITION_LIMIT

router = APIRouter(prefix="/api/projects/{project_id}/m43", tags=["M4.3 Bulk Processing"])


class StartRequest(BaseModel):
    version_id: str = Field(min_length=36,max_length=36)
    idempotency_key: str = Field(min_length=12,max_length=64,pattern=r"^[A-Za-z0-9-]+$")


def active_job(db: Session, project_id: str):
    return db.scalar(select(BulkJob).where(
        BulkJob.project_id == project_id,
        BulkJob.status.in_(("queued","running"))
    ).order_by(BulkJob.created_at.desc()).limit(1))


def guard_no_active(db: Session, project_id: str):
    if active_job(db,project_id):
        raise HTTPException(409, "An M4.3 bulk job is active for this project")


def _rights(db: Session, user: User, version_id: str):
    version = db.get(CatalogVersion,version_id)
    if version is None:
        raise HTTPException(404,"Catalog version not found")
    source = db.get(CatalogSource,version.source_id)
    if source is None or source.organization_id != user.organization_id:
        raise HTTPException(404,"Catalog version not found")
    if source.institution == DEMO_INSTITUTION:
        if source.permission_scope != DEMO_SCOPE or source.license_status != "verified":
            raise HTTPException(403,"Synthetic catalog permission not active")
    else:
        eligible_version(db,user.organization_id,version_id)
    return version, source


def _show(job: BulkJob):
    return {
        "id":job.id,"status":job.status,"project_id":job.project_id,
        "run_id":job.run_id,"import_id":job.import_id,
        "version_id":job.version_id,"processed_rows":job.processed_rows,
        "total_rows":job.total_rows,"candidate_count":job.candidate_count,
        "percent":round(100*job.processed_rows/max(1,job.total_rows),1),
        "failure_reason":job.failure_reason,
        "created_at":job.created_at,"completed_at":job.completed_at,
        "requires_local_worker":job.status in ("queued","running"),
        "published":job.status=="completed",
    }


@router.get("/catalogs")
def catalogs(project_id: str, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    tenant_project(db,user,project_id)
    imports=db.scalars(select(CatalogImport).where(
        CatalogImport.organization_id==user.organization_id,
        CatalogImport.status=="approved",
        CatalogImport.approval_scope=="internal_matching"
    ).order_by(CatalogImport.created_at.desc())).all()
    output=[]
    for imp in imports:
        try:
            v,source=_rights(db,user,imp.version_id)
        except HTTPException:
            continue
        count=db.scalar(select(func.count(CatalogPosition.id)).where(
            CatalogPosition.version_id==v.id)) or 0
        if 1 <= count <= POSITION_LIMIT:
            output.append({"version_id":v.id,"institution":source.institution,
                           "period":v.period,"year":v.year,"positions":count})
    return output


@router.post("/jobs",status_code=202)
def enqueue(project_id: str, payload: StartRequest,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db,user,project_id)
    previous=db.scalar(select(BulkJob).where(
        BulkJob.project_id==project_id,BulkJob.idempotency_key==payload.idempotency_key))
    if previous:
        if previous.version_id!=payload.version_id:
            raise HTTPException(409,"Idempotency key already used for another catalog")
        return _show(previous)
    guard_no_active(db,project_id)
    version,source=_rights(db,user,payload.version_id)
    latest_import=db.scalar(select(ImportBatch).where(
        ImportBatch.project_id==project_id).order_by(
        ImportBatch.created_at.desc(),ImportBatch.id.desc()))
    if not latest_import:
        raise HTTPException(409,"Import Excel metraj first")
    if not 1 <= latest_import.row_count <= ROW_LIMIT:
        raise HTTPException(422,f"M4.3 requires 1 to {ROW_LIMIT} metraj rows")
    positions=db.scalars(select(CatalogPosition.id).where(
        CatalogPosition.version_id==version.id).limit(POSITION_LIMIT+1)).all()
    if not 1 <= len(positions) <= POSITION_LIMIT:
        raise HTTPException(422,f"M4.3 requires 1 to {POSITION_LIMIT} catalog positions")
    items=db.scalars(select(WorkItem).where(
        WorkItem.import_id==latest_import.id).order_by(
        WorkItem.source_row,WorkItem.id)).all()
    if len(items)!=latest_import.row_count:
        raise HTTPException(409,"Metraj row count mismatch")
    parent=latest_run(db,project_id)
    run=MatchRun(project_id=project_id,import_id=latest_import.id,
                 version_id=version.id,created_by_id=user.id,
                 parent_run_id=parent.id if parent else None,
                 algorithm=ALGORITHM,row_count=len(items),candidate_count=0)
    db.add(run)
    db.flush()
    for item in items:
        db.add(frozen_snapshot(run.id,effective_item(db,item)))
    job=BulkJob(organization_id=user.organization_id,
                project_id=project_id,import_id=latest_import.id,
                version_id=version.id,run_id=run.id,created_by_id=user.id,
                idempotency_key=payload.idempotency_key,
                total_rows=len(items),status="queued",processed_rows=0,candidate_count=0)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        matching=db.scalar(select(BulkJob).where(
            BulkJob.project_id==project_id,BulkJob.idempotency_key==payload.idempotency_key))
        if matching:
            return _show(matching)
        raise HTTPException(409,"Another batch job has started") from None
    return _show(job)


@router.get("/jobs")
def recent_jobs(project_id: str,
                user: User = Depends(current_user),db: Session = Depends(get_db)):
    tenant_project(db,user,project_id)
    jobs=db.scalars(select(BulkJob).where(
        BulkJob.project_id==project_id).order_by(
        BulkJob.created_at.desc(),BulkJob.id.desc()).limit(20)).all()
    return [_show(j) for j in jobs]


@router.get("/jobs/{job_id}")
def job_status(project_id: str,job_id: str,
               user: User = Depends(current_user),db: Session = Depends(get_db)):
    tenant_project(db,user,project_id)
    job=db.scalar(select(BulkJob).where(
        BulkJob.id==job_id,BulkJob.project_id==project_id,
        BulkJob.organization_id==user.organization_id))
    if job is None:
        raise HTTPException(404,"Job not found")
    return _show(job)


@router.post("/jobs/{job_id}/retry",status_code=202)
def retry_failed(project_id: str,job_id: str,
                 user: User = Depends(current_user),db: Session = Depends(get_db)):
    tenant_project(db,user,project_id)
    job=db.scalar(select(BulkJob).where(
        BulkJob.id==job_id,BulkJob.project_id==project_id,
        BulkJob.organization_id==user.organization_id))
    if not job:
        raise HTTPException(404,"Job not found")
    if job.status!="failed":
        raise HTTPException(409,"Only failed jobs can be retried; blocked jobs require a new run")
    guard_no_active(db,project_id)
    _rights(db,user,job.version_id)
    current=db.scalar(select(ImportBatch).where(
        ImportBatch.project_id==project_id).order_by(
        ImportBatch.created_at.desc(),ImportBatch.id.desc()))
    if not current or current.id!=job.import_id:
        raise HTTPException(409,"Metraj import changed; create a new job")
    # Worker verifies every frozen input before processing.
    job.status="queued"
    job.failure_reason=None
    job.lease_owner=None
    job.lease_until=None
    db.commit()
    return _show(job)
