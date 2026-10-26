"""M4.2 paginated candidate review queue, source evidence, and decision history.

No new approval authority: writes go through M2's guarded decision endpoint.
Pagination is on CANDIDATES, not imported work items. Legacy M4.1 supports
100 metraj rows; M4.3 bulk supports 500. Both allow 500 catalog positions.
"""
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from .models import (
    User, MatchRun, MatchCandidate, MatchDecision, MatchRunItemSnapshot,
    WorkItem, CatalogPosition, CatalogVersion, CatalogSource, CatalogImport,
    ImportBatch, TechnicalEvidence,
)
from .m2 import tenant_project, latest_run, DEMO_INSTITUTION, DEMO_SCOPE
from .revisions import effective_item, fingerprint, previously_frozen
from .evidence_v41 import ALGORITHM, verify_evidence
from .m43_worker import ALGORITHM as BULK_ALGORITHM

router = APIRouter(prefix="/api/projects/{project_id}/m42", tags=["M4.2 Engineer Review"])


def _context(db: Session, user: User, project_id: str):
    tenant_project(db, user, project_id)
    run = latest_run(db, project_id)
    if not run or run.algorithm not in (ALGORITHM, BULK_ALGORITHM):
        return None
    version = db.get(CatalogVersion, run.version_id)
    source = db.get(CatalogSource, version.source_id)
    if source is None or source.organization_id != user.organization_id:
        raise HTTPException(403, "Catalog is outside organization")
    if source.institution == DEMO_INSTITUTION:
        rights_active = source.permission_scope == DEMO_SCOPE and source.license_status == "verified"
    else:
        review = db.scalar(select(CatalogImport).where(
            CatalogImport.organization_id == user.organization_id,
            CatalogImport.version_id == run.version_id,
            CatalogImport.status == "approved",
            CatalogImport.approval_scope == "internal_matching"))
        rights_active = bool(review and review.approval_evidence and review.reviewed_by
                             and review.sha256 == version.sha256)
    last_import = db.scalar(select(ImportBatch).where(
        ImportBatch.project_id == project_id).order_by(
        ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    from .import_policy import source_excluded
    outdated = (last_import is None or last_import.id != run.import_id
                or source_excluded(db, last_import.id if last_import else None))
    return run, version, source, rights_active, outdated


def _latest_decision_id():
    return (select(MatchDecision.id)
            .where(MatchDecision.candidate_id == MatchCandidate.id)
            .order_by(MatchDecision.created_at.desc(), MatchDecision.id.desc())
            .limit(1).correlate(MatchCandidate).scalar_subquery())


def _candidate_rows(run_id):
    return (select(MatchCandidate, WorkItem, CatalogPosition,
                   MatchRunItemSnapshot, TechnicalEvidence, MatchDecision)
            .select_from(MatchCandidate)
            .join(WorkItem, WorkItem.id == MatchCandidate.work_item_id)
            .join(CatalogPosition, CatalogPosition.id == MatchCandidate.position_id)
            .outerjoin(MatchRunItemSnapshot,
                       (MatchRunItemSnapshot.run_id == MatchCandidate.run_id) &
                       (MatchRunItemSnapshot.work_item_id == MatchCandidate.work_item_id))
            .outerjoin(TechnicalEvidence, TechnicalEvidence.candidate_id == MatchCandidate.id)
            .outerjoin(MatchDecision, MatchDecision.id == _latest_decision_id())
            .where(MatchCandidate.run_id == run_id))


def _proof(entry: TechnicalEvidence | None):
    if entry is None:
        return None
    try:
        proof = json.loads(entry.payload_json)
    except (ValueError, TypeError):
        raise HTTPException(409, "Recorded evidence cannot be decoded") from None
    if (not verify_evidence(proof)
            or entry.evidence_sha256 != proof.get("evidence_sha256")
            or entry.status != proof.get("status")
            or entry.schema_version != proof.get("schema")):
        raise HTTPException(409, "Recorded evidence integrity mismatch")
    return proof


@router.get("/queue")
def queue(project_id: str,
          status: Literal["all", "blocked", "review", "compatible", "missing"] = "all",
          decision: Literal["all", "undecided", "approved", "rejected"] = "all",
          q: str = Query(default="", max_length=120),
          page: int = Query(default=1, ge=1, le=10000),
          page_size: int = Query(default=20, ge=1, le=50),
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    context = _context(db, user, project_id)
    if context is None:
        return {"run": None, "total": 0, "page": page, "page_size": page_size,
                "rows": [], "summary": {}, "message": "Run M4.1 analysis first"}
    run, version, source, rights_active, outdated = context
    base = _candidate_rows(run.id)
    status_expr = func.coalesce(TechnicalEvidence.status, "missing")
    if status != "all":
        base = base.where(status_expr == status)
    if decision == "approved":
        base = base.where(MatchDecision.action == "approve")
    elif decision == "rejected":
        base = base.where(MatchDecision.action == "reject")
    elif decision == "undecided":
        base = base.where(MatchDecision.id.is_(None))
    search = q.strip().lower()
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        base = base.where(or_(
            func.lower(func.coalesce(MatchRunItemSnapshot.description,
                                     WorkItem.raw_description)).like(pattern, escape="\\"),
            func.lower(CatalogPosition.description).like(pattern, escape="\\"),
            func.lower(CatalogPosition.code).like(pattern, escape="\\")))
    total = db.scalar(base.with_only_columns(func.count(MatchCandidate.id)).order_by(None)) or 0

    # Summary is independent from filters and aggregated in SQL, not sent as hundreds of rows.
    summary_status = db.execute(
        select(status_expr, func.count(MatchCandidate.id))
        .select_from(MatchCandidate)
        .outerjoin(TechnicalEvidence, TechnicalEvidence.candidate_id == MatchCandidate.id)
        .where(MatchCandidate.run_id == run.id)
        .group_by(status_expr)).all()
    summary_decisions = db.execute(
        select(MatchDecision.action, func.count(MatchCandidate.id))
        .select_from(MatchCandidate)
        .outerjoin(MatchDecision, MatchDecision.id == _latest_decision_id())
        .where(MatchCandidate.run_id == run.id)
        .group_by(MatchDecision.action)).all()

    page_rows = db.execute(
        base.order_by(WorkItem.source_row.asc(), MatchCandidate.rank.asc(),
                      MatchCandidate.id.asc())
        .limit(page_size).offset((page - 1) * page_size)).all()
    rows = []
    for candidate, item, position, snapshot, entry, last in page_rows:
        # Fail closed for tampered evidence, including rows with a status filter.
        proof = _proof(entry)
        stale = (not rights_active or outdated or snapshot is None
                 or fingerprint(effective_item(db, item)) != previously_frozen(item, snapshot))
        status_value = proof["status"] if proof else "missing"
        approvable = (not stale and status_value == "compatible" and
                      candidate.approvable and not (snapshot.review_required if snapshot else item.review_required))
        rows.append({
            "candidate_id": candidate.id, "work_item_id": item.id,
            "source_row": item.source_row,
            "metraj": snapshot.description if snapshot else item.raw_description,
            "unit": snapshot.unit if snapshot else item.normalized_unit,
            "code": position.code, "position": position.description,
            "rank": candidate.rank, "similarity": float(candidate.similarity),
            "status": status_value, "stale": stale, "can_approve": approvable,
            "last_decision": ({"action": last.action, "reason": last.reason,
                               "at": last.created_at, "by": last.decided_by_id}
                              if last else None),
        })
    return {
        "run": {"id": run.id, "algorithm": run.algorithm,
                "catalog": source.institution, "year": version.year,
                "period": version.period, "rights_active": rights_active,
                "outdated_import": outdated, "row_count": run.row_count,
                "row_limit": 500 if run.algorithm == BULK_ALGORITHM else 100,
                "catalog_position_limit": 500, "candidate_count": run.candidate_count},
        "page": page, "page_size": page_size, "total": total, "rows": rows,
        "summary": {
            "statuses": {key: dict(summary_status).get(key, 0)
                         for key in ("compatible", "review", "blocked", "missing")},
            "decisions": {
                "approved": dict(summary_decisions).get("approve", 0),
                "rejected": dict(summary_decisions).get("reject", 0),
                "undecided": dict(summary_decisions).get(None, 0),
            },
        },
    }


@router.get("/candidates/{candidate_id}")
def candidate_detail(project_id: str, candidate_id: str,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    context = _context(db, user, project_id)
    if context is None:
        raise HTTPException(409, "No M4.1 run to inspect")
    run, version, source, rights_active, outdated = context
    candidate = db.scalar(select(MatchCandidate).where(
        MatchCandidate.id == candidate_id, MatchCandidate.run_id == run.id))
    if candidate is None:
        raise HTTPException(404, "Candidate not in latest run")
    position = db.get(CatalogPosition, candidate.position_id)
    item = db.get(WorkItem, candidate.work_item_id)
    snapshot = db.scalar(select(MatchRunItemSnapshot).where(
        MatchRunItemSnapshot.run_id == run.id,
        MatchRunItemSnapshot.work_item_id == item.id))
    evidence = db.scalar(select(TechnicalEvidence).where(
        TechnicalEvidence.candidate_id == candidate.id))
    proof = _proof(evidence)
    stale = (not rights_active or outdated or snapshot is None
             or fingerprint(effective_item(db, item)) != previously_frozen(item, snapshot))

    # All decision events for same item+position across past runs in this project,
    # sorted newest first. Historical decisions are not treated as current approval.
    events = db.execute(
        select(MatchDecision, MatchRun.id, User.email)
        .join(MatchCandidate, MatchCandidate.id == MatchDecision.candidate_id)
        .join(MatchRun, MatchRun.id == MatchCandidate.run_id)
        .join(User, User.id == MatchDecision.decided_by_id)
        .where(MatchRun.project_id == project_id,
               MatchCandidate.work_item_id == candidate.work_item_id,
               MatchCandidate.position_id == candidate.position_id)
        .order_by(MatchDecision.created_at.desc(), MatchDecision.id.desc())
        .limit(50)).all()
    return {
        "candidate_id": candidate.id,
        "code": position.code, "position": position.description,
        "metraj": snapshot.description if snapshot else item.raw_description,
        "source_row": item.source_row,
        "rights_active": rights_active,
        "stale": stale,
        "can_approve": bool(proof and proof["status"] == "compatible"
                            and candidate.approvable and not stale
                            and not (snapshot.review_required if snapshot else item.review_required)),
        "evidence": proof,
        "history": [{"action": d.action, "reason": d.reason, "at": d.created_at,
                     "reviewer": email, "run_id": prior_run_id,
                     "current_run": prior_run_id == run.id}
                    for d, prior_run_id, email in events],
        "history_limited": len(events) == 50,
    }
