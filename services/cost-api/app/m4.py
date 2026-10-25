"""M4 isolated technical comparison runs and explainable evidence API."""
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from .database import get_db
from .security import current_user
from .models import (User, CatalogVersion, CatalogSource, CatalogPosition,
                     ImportBatch, WorkItem, MatchRun, MatchCandidate,
                     TechnicalComparison)
from .matching import similarity, MAX_MATCH_ROWS
from .technical import compare, VERSION
from .revisions import effective_item, frozen_snapshot
from .m2 import tenant_project, latest_run, DEMO_INSTITUTION, DEMO_SCOPE

router = APIRouter(prefix="/api", tags=["M4 Technical Comparison"])
MAX_POSITIONS = 500


@router.post("/projects/{project_id}/m4/run", status_code=201)
def run_comparison(project_id: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    prior = latest_run(db, project_id)
    if not prior:
        raise HTTPException(409, "First run M2/M3 catalog matching")
    version = db.get(CatalogVersion, prior.version_id)
    source = db.get(CatalogSource, version.source_id)
    if source.institution == DEMO_INSTITUTION:
        if source.permission_scope != DEMO_SCOPE or source.license_status != "verified":
            raise HTTPException(403, "Demo catalog authorization failed")
    else:
        from .m3 import eligible_version
        eligible_version(db, user.organization_id, version.id)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                      .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    if not batch or prior.import_id != batch.id:
        raise HTTPException(409, "Run M2/M3 matching for the latest metraj import first")
    if batch.row_count > MAX_MATCH_ROWS:
        raise HTTPException(422, "Maximum 100 metraj items")
    positions = db.scalars(select(CatalogPosition).where(CatalogPosition.version_id == version.id)
                           .order_by(CatalogPosition.code).limit(MAX_POSITIONS + 1)).all()
    if not positions or len(positions) > MAX_POSITIONS:
        raise HTTPException(422, "M4 pilot requires 1–500 catalog positions")
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)
                       .order_by(WorkItem.source_row)).all()
    run = MatchRun(project_id=project_id, import_id=batch.id, version_id=version.id,
                   parent_run_id=prior.id, changed_item_count=0, created_by_id=user.id,
                   row_count=len(items), candidate_count=0, algorithm=VERSION)
    db.add(run)
    db.flush()
    stats = {"compatible": 0, "review": 0, "blocked": 0}
    for item in items:
        active = effective_item(db, item)
        db.add(frozen_snapshot(run.id, active))
        shortlist = []
        for pos in positions:
            lex = similarity(active.raw_description, pos.description)
            if lex < 0.18:
                continue
            evidence = compare(
                active.raw_description, active.normalized_unit,
                pos.description, pos.unit,
                quantity_known=active.quantity is not None,
                review_required=active.review_required,
            )
            shortlist.append((lex, pos.code, pos, evidence))
        shortlist.sort(key=lambda result: (-result[0], result[1]))
        for rank, (lex, _code, pos, report) in enumerate(shortlist[:3], 1):
            candidate = MatchCandidate(
                run_id=run.id, work_item_id=item.id, position_id=pos.id,
                rank=rank, similarity=lex,
                reasons_json=json.dumps(report["matches"], ensure_ascii=False),
                warnings_json=json.dumps(report["blockers"] + report["review_flags"], ensure_ascii=False),
                approvable=report["manual_approval_allowed"],
            )
            db.add(candidate)
            db.flush()
            db.add(TechnicalComparison(
                candidate_id=candidate.id, version=VERSION, status=report["status"],
                report_json=json.dumps(report, ensure_ascii=False)))
            stats[report["status"]] += 1
            run.candidate_count += 1
    db.commit()
    return {"id": run.id, "parent_run_id": prior.id, "algorithm": VERSION,
            "row_count": run.row_count, "candidate_count": run.candidate_count,
            "technical_statuses": stats, "human_approval_required": True,
            "legacy_runs_unchanged": True}


@router.get("/projects/{project_id}/m4/latest")
def latest_comparison(project_id: str, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    from .m2 import latest
    payload = latest(project_id=project_id, user=user, db=db)
    run = payload.get("run")
    if not run or run["algorithm"] != VERSION:
        return {"run": None, "items": [], "message": "No M4 comparison run yet"}
    candidates = [cand for item in payload["items"] for cand in item["candidates"]]
    reports = db.scalars(select(TechnicalComparison).where(
        TechnicalComparison.candidate_id.in_([c["id"] for c in candidates])
    )).all() if candidates else []
    by_candidate = {report.candidate_id: json.loads(report.report_json) for report in reports}
    for item in payload["items"]:
        for candidate in item["candidates"]:
            candidate["technical"] = by_candidate.get(candidate["id"])
    return payload


@router.get("/m4/quality")
def quality(user: User = Depends(current_user)):
    from .m4_quality import evaluate_fixture
    return evaluate_fixture()
