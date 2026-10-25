"""M4.3 bounded durable offline worker.

A separate local Python process drains the DB queue. API workers never execute
500-row analysis in a web request. Each CHUNK transaction atomically commits
candidate evidence and cursor, so a process crash cannot half-commit a row.
For this SQLite pilot run ONE worker only (no distributed queue guarantees).
"""
import argparse
import json
import time
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import (
    BulkJob, MatchRun, WorkItem, MatchRunItemSnapshot, MatchCandidate,
    CatalogPosition, CatalogVersion, CatalogSource, CatalogImport,
    TechnicalComparison, TechnicalEvidence, ImportBatch, WorkItemRevision,
)
from .m2 import DEMO_INSTITUTION, DEMO_SCOPE
from .m3 import eligible_version
from .matching import similarity
from .technical import compare, VERSION
from .evidence_v41 import analyze, ALGORITHM as BASE_ALGORITHM
from .revisions import effective_item, fingerprint, previously_frozen

ALGORITHM = BASE_ALGORITHM + "+bulk-v0.1"
ROW_LIMIT = 500
POSITION_LIMIT = 500
CHUNK = 20
LEASE_SECONDS = 600


class JobBlocked(Exception):
    pass


def _utc():
    return datetime.utcnow()


def _rights_check(db: Session, job: BulkJob):
    version = db.get(CatalogVersion, job.version_id)
    if version is None:
        raise JobBlocked("Catalog version missing")
    source = db.get(CatalogSource, version.source_id)
    if source is None or source.organization_id != job.organization_id:
        raise JobBlocked("Catalog outside organization")
    if source.institution == DEMO_INSTITUTION:
        if source.permission_scope != DEMO_SCOPE or source.license_status != "verified":
            raise JobBlocked("Synthetic catalog permission revoked")
    else:
        try:
            eligible_version(db, job.organization_id, version.id)
        except Exception as exc:
            raise JobBlocked("Operator-approved catalog rights unavailable") from exc
    return version


def _inputs_unchanged(db: Session, job: BulkJob):
    current = db.scalar(select(ImportBatch).where(
        ImportBatch.project_id == job.project_id).order_by(
        ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    if not current or current.id != job.import_id:
        raise JobBlocked("New metraj import superseded the batch")
    snapshots = {s.work_item_id: s for s in db.scalars(
        select(MatchRunItemSnapshot).where(MatchRunItemSnapshot.run_id == job.run_id)).all()}
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == job.import_id)).all()
    if len(items) != job.total_rows or len(snapshots) != job.total_rows:
        raise JobBlocked("Frozen input row count changed")
    for item in items:
        if fingerprint(effective_item(db, item)) != previously_frozen(item, snapshots[item.id]):
            raise JobBlocked("Metraj revision changed during background processing")


def _mark(db: Session, job_id: str, status: str, reason: str):
    # Must be called only after a rollback of failed batch calculation.
    job = db.get(BulkJob, job_id)
    if job and job.status == "running":
        job.status = status
        job.failure_reason = reason[:300]
        job.lease_owner = None
        job.lease_until = None
        db.commit()


def process_chunk(db: Session, job_id: str, *, chunk_size: int = CHUNK) -> bool:
    """Returns True when one chunk/status transition was handled."""
    if not 1 <= chunk_size <= CHUNK:
        raise ValueError("Chunk must be between 1 and 20")
    token = str(uuid4())
    now = _utc()
    claimed = db.execute(update(BulkJob).where(
        BulkJob.id == job_id,
        (BulkJob.status == "queued") |
        ((BulkJob.status == "running") & (BulkJob.lease_until < now)),
    ).values(status="running",lease_owner=token,
             lease_until=now + timedelta(seconds=LEASE_SECONDS),
             started_at=now))
    db.commit()
    if not claimed.rowcount:
        return False
    try:
        job = db.get(BulkJob, job_id)
        run = db.get(MatchRun, job.run_id)
        if not run or run.algorithm != ALGORITHM or run.project_id != job.project_id:
            raise JobBlocked("Run linkage invalid")
        _rights_check(db, job)
        _inputs_unchanged(db, job)
        positions = db.scalars(select(CatalogPosition).where(
            CatalogPosition.version_id == job.version_id).order_by(
            CatalogPosition.code, CatalogPosition.id).limit(POSITION_LIMIT+1)).all()
        if not 1 <= len(positions) <= POSITION_LIMIT:
            raise JobBlocked("Catalog position limit exceeded")
        items = db.scalars(select(WorkItem).where(
            WorkItem.import_id == job.import_id).order_by(
            WorkItem.source_row, WorkItem.id)
            .offset(job.processed_rows).limit(chunk_size)).all()
        if not items and job.processed_rows != job.total_rows:
            raise JobBlocked("Metraj rows missing")
        version = db.get(CatalogVersion, job.version_id)
        imp = db.get(ImportBatch, job.import_id)
        for item in items:
            active = effective_item(db,item)
            # Score every catalog position, then evaluate the top three only.
            scored = [(similarity(active.raw_description,p.description),p.code,p.id,p)
                      for p in positions]
            scored = sorted((x for x in scored if x[0] >= 0.18),
                            key=lambda x:(-x[0],x[1],x[2]))[:3]
            for rank,(lex,code,_id,pos) in enumerate(scored,1):
                report = compare(
                    active.raw_description,active.normalized_unit,
                    pos.description,pos.unit,quantity_known=active.quantity is not None,
                    review_required=active.review_required)
                proof = analyze(
                    active.raw_description,active.normalized_unit,
                    pos.description,pos.unit,quantity_known=active.quantity is not None,
                    review_required=active.review_required,
                    source_refs={
                        "metraj":{"import_id":imp.id,"import_sha256":imp.sha256,
                                  "source_row":active.source_row,"work_item_id":item.id,
                                  "revision_id":active.revision_id},
                        "catalog":{"version_id":version.id,"version_sha256":version.sha256,
                                   "position_id":pos.id,"position_code":pos.code},
                    })
                report["status"] = proof["status"]
                report["manual_approval_allowed"] = proof["approval_allowed"]
                report["blockers"] = proof["blockers"]
                report["review_flags"] = proof["review_flags"]
                c = MatchCandidate(
                    run_id=run.id,work_item_id=item.id,position_id=pos.id,
                    rank=rank,similarity=lex,
                    reasons_json=json.dumps(report["matches"],ensure_ascii=False),
                    warnings_json=json.dumps(report["blockers"]+report["review_flags"],ensure_ascii=False),
                    approvable=proof["approval_allowed"])
                db.add(c)
                db.flush()
                db.add(TechnicalComparison(candidate_id=c.id,version=VERSION,
                    status=report["status"],report_json=json.dumps(report,ensure_ascii=False)))
                db.add(TechnicalEvidence(candidate_id=c.id,schema_version=proof["schema"],
                    status=proof["status"],evidence_sha256=proof["evidence_sha256"],
                    payload_json=json.dumps(proof,ensure_ascii=False)))
                job.candidate_count += 1
                run.candidate_count += 1
        job.processed_rows += len(items)
        if job.processed_rows == job.total_rows:
            # Complete is the ONLY state in which the run becomes visible/approvable.
            _rights_check(db, job)
            _inputs_unchanged(db, job)
            job.status = "completed"
            job.completed_at = _utc()
        else:
            job.status = "queued"
        job.lease_owner = None
        job.lease_until = None
        db.commit()
        return True
    except JobBlocked as exc:
        db.rollback()
        _mark(db,job_id,"blocked",str(exc))
        return True
    except Exception as exc:
        db.rollback()
        _mark(db,job_id,"failed",type(exc).__name__)
        return True


def run_available(*, max_steps: int = 1000, chunk_size: int = CHUNK) -> int:
    steps = 0
    while steps < max_steps:
        with SessionLocal() as db:
            now = _utc()
            job_id = db.scalar(select(BulkJob.id).where(
                (BulkJob.status == "queued") |
                ((BulkJob.status == "running") & (BulkJob.lease_until < now))
            ).order_by(BulkJob.created_at,BulkJob.id).limit(1))
            if not job_id:
                break
            if not process_chunk(db,job_id,chunk_size=chunk_size):
                break
            steps+=1
    return steps


def main():
    parser=argparse.ArgumentParser(description="ARKEMX offline single-worker M4.3 queue")
    parser.add_argument("--watch",action="store_true",help="Keep polling; run in separate terminal")
    parser.add_argument("--chunk-size",type=int,default=CHUNK)
    args=parser.parse_args()
    if not 1 <= args.chunk_size <= CHUNK:
        parser.error("chunk-size must be 1..20")
    print("M4.3 local worker started (one worker per SQLite DB).",flush=True)
    while True:
        steps=run_available(max_steps=1000,chunk_size=args.chunk_size)
        print(f"Processed {steps} chunks; no active work remains.",flush=True)
        if not args.watch:
            break
        time.sleep(2)


if __name__=="__main__":
    main()
