"""M2.1 human-verified metraj corrections and incremental position re-matching.

All revisions are append-only. Full original WorkItem rows remain untouched.
No government catalog, price, or automatic quantity inference is involved.
"""
import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from .excel import parse_quantity, normalize_unit
from .matching import find_candidates, ALGORITHM, MAX_MATCH_ROWS
from .revisions import latest_revision, effective_item, frozen_snapshot, fingerprint, previously_frozen
from .models import (User, Project, ImportBatch, WorkItem, WorkItemRevision,
                     MatchRun, MatchRunItemSnapshot, MatchCandidate, CatalogPosition,
                     CatalogVersion, CatalogSource)

router = APIRouter(prefix="/api", tags=["M2.1 Metraj Revisions"])


class RevisionRequest(BaseModel):
    description: str = Field(min_length=3, max_length=10000)
    quantity: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=8, max_length=500)
    expected_revision: int = Field(ge=0, le=99999)


def project_or_404(db: Session, project_id: str, user: User) -> Project:
    row = db.scalar(select(Project).where(Project.id == project_id,
                                         Project.organization_id == user.organization_id))
    if row is None:
        raise HTTPException(404, "Project not found")
    return row


def latest_import(db: Session, project_id: str):
    return db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                     .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))


def latest_project_item(db: Session, project_id: str, item_id: str):
    batch = latest_import(db, project_id)
    if not batch:
        raise HTTPException(404, "No import found")
    item = db.scalar(select(WorkItem).where(WorkItem.id == item_id, WorkItem.import_id == batch.id))
    if not item:
        raise HTTPException(404, "Item not found in latest import")
    return item


def effective_view(db: Session, item: WorkItem):
    rev = latest_revision(db, item.id)
    active = effective_item(db, item, rev)
    return {
        "id": item.id, "source_row": item.source_row,
        "original": {
            "description": item.raw_description, "quantity": item.raw_quantity,
            "normalized_quantity": str(item.quantity) if item.quantity is not None else None,
            "unit": item.raw_unit, "normalized_unit": item.normalized_unit,
            "review_required": item.review_required,
        },
        "effective": {
            "description": active.raw_description,
            "quantity": str(active.quantity) if active.quantity is not None else None,
            "unit": active.normalized_unit,
            "review_required": active.review_required,
        },
        "revision": active.revision, "reason": rev.reason if rev else None,
        "edited_at": rev.created_at if rev else None,
    }


@router.get("/projects/{project_id}/m21/items")
def list_corrections(project_id: str, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    project_or_404(db, project_id, user)
    batch = latest_import(db, project_id)
    if batch is None:
        return []
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)
                       .order_by(WorkItem.source_row)).all()
    return [effective_view(db, item) for item in items]


@router.get("/projects/{project_id}/m21/items/{item_id}/history")
def revision_history(project_id: str, item_id: str, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    project_or_404(db, project_id, user)
    # Historical records remain read-only; no requirement to be in latest batch here.
    item = db.scalar(select(WorkItem).join(ImportBatch, ImportBatch.id == WorkItem.import_id)
                     .where(WorkItem.id == item_id, ImportBatch.project_id == project_id))
    if not item:
        raise HTTPException(404, "Item not found")
    rows = db.scalars(select(WorkItemRevision).where(WorkItemRevision.work_item_id == item_id)
                      .order_by(WorkItemRevision.revision)).all()
    return {
        "item_id": item.id, "source_row": item.source_row,
        "original": {"description": item.raw_description, "quantity": item.raw_quantity,
                     "unit": item.raw_unit},
        "revisions": [{"id": r.id, "revision": r.revision, "description": r.description,
                       "quantity": str(r.quantity), "unit": r.unit, "reason": r.reason,
                       "corrected_by": r.corrected_by_id, "created_at": r.created_at} for r in rows]
    }


@router.post("/projects/{project_id}/m21/items/{item_id}/revisions", status_code=201)
def correct_item(project_id: str, item_id: str, payload: RevisionRequest,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_or_404(db, project_id, user)
    item = latest_project_item(db, project_id, item_id)
    prior = latest_revision(db, item.id)
    current_no = prior.revision if prior else 0
    if current_no != payload.expected_revision:
        raise HTTPException(409, "Revision conflict: reload the latest item before saving")
    amount, amount_issues = parse_quantity(payload.quantity)
    if amount_issues or amount is None:
        raise HTTPException(422, "Quantity requires explicit, unambiguous correction: " + ", ".join(amount_issues))
    unit, unit_issues = normalize_unit(payload.unit)
    if unit_issues or unit is None:
        raise HTTPException(422, "Unit must be a recognized engineering unit: " + ", ".join(unit_issues))
    description = payload.description.strip()
    if description.startswith(("=", "+", "-", "@")):
        raise HTTPException(422, "Description may not start with a spreadsheet formula marker")
    original = effective_item(db, item, prior)
    if (description, amount, unit) == (original.raw_description, original.quantity, original.normalized_unit):
        raise HTTPException(409, "No field changed; do not create a duplicate revision")
    revision = WorkItemRevision(
        work_item_id=item.id, revision=current_no + 1,
        description=description, quantity=amount, unit=unit,
        corrected_by_id=user.id, reason=payload.reason.strip()
    )
    db.add(revision)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent revision conflict; reload before saving") from None
    return {"id": revision.id, "work_item_id": item.id, "revision": revision.revision,
            "requires_rematch": True, "original_excel_preserved": True}


@router.post("/projects/{project_id}/m21/rematch", status_code=201)
def incremental_rematch(project_id: str, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    project_or_404(db, project_id, user)
    from .m2 import latest_run, DEMO_INSTITUTION, DEMO_SCOPE
    prior_run = latest_run(db, project_id)
    batch = latest_import(db, project_id)
    if prior_run is None or batch is None or prior_run.import_id != batch.id:
        raise HTTPException(409, "First run full M2 matching for the current import")
    if prior_run.algorithm in ("technical-rules-v0.1", "technical-rules-v0.1+evidence-v0.1",
                                "technical-rules-v0.1+evidence-v0.1+bulk-v0.1"):
        raise HTTPException(409, "After M4 analysis, rerun M4 for revised metraj; prior technical evidence cannot be copied")
    if batch.row_count > MAX_MATCH_ROWS:
        raise HTTPException(422, "M2 pilot limit exceeded")
    version = db.get(CatalogVersion, prior_run.version_id)
    source = db.get(CatalogSource, version.source_id)
    if source.institution == DEMO_INSTITUTION:
        if source.permission_scope != DEMO_SCOPE:
            raise HTTPException(403, "Demo catalog scope is invalid")
    else:
        from .m3 import eligible_version
        eligible_version(db, user.organization_id, prior_run.version_id)
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)
                       .order_by(WorkItem.source_row)).all()
    snapshots = {s.work_item_id: s for s in db.scalars(
        select(MatchRunItemSnapshot).where(MatchRunItemSnapshot.run_id == prior_run.id)).all()}
    current = {item.id: effective_item(db, item) for item in items}
    changed = [item for item in items if fingerprint(current[item.id]) !=
               previously_frozen(item, snapshots.get(item.id))]
    if not changed:
        raise HTTPException(409, "No changed metraj values since the previous matching run")
    positions = db.scalars(select(CatalogPosition).where(CatalogPosition.version_id == version.id)
                           .order_by(CatalogPosition.code)).all()
    if not positions:
        raise HTTPException(409, "Catalog is empty")
    old_candidates = db.scalars(select(MatchCandidate).where(
        MatchCandidate.run_id == prior_run.id).order_by(MatchCandidate.rank)).all()
    by_item = {}
    for old in old_candidates:
        by_item.setdefault(old.work_item_id, []).append(old)

    run = MatchRun(project_id=project_id, import_id=batch.id, version_id=version.id,
                   parent_run_id=prior_run.id, changed_item_count=len(changed),
                   created_by_id=user.id, row_count=len(items),
                   algorithm=ALGORITHM + "+incremental", candidate_count=0)
    db.add(run)
    db.flush()
    total = 0
    recalc_ids = {i.id for i in changed}
    for item in items:
        effective = current[item.id]
        db.add(frozen_snapshot(run.id, effective))
        if item.id in recalc_ids:
            entries = find_candidates(effective, positions, use_ollama=False)
            for rank, entry in enumerate(entries, start=1):
                db.add(MatchCandidate(
                    run_id=run.id, work_item_id=item.id, position_id=entry["position_id"],
                    rank=rank, similarity=entry["similarity"], approvable=entry["approvable"],
                    reasons_json=json.dumps(entry["reasons"], ensure_ascii=False),
                    warnings_json=json.dumps(entry["warnings"], ensure_ascii=False)
                ))
                total += 1
        else:
            # Retain previously computed candidate evidence. Prior approvals remain
            # in the old run; this new run requires fresh human sign-off.
            for old in by_item.get(item.id, []):
                db.add(MatchCandidate(
                    run_id=run.id, work_item_id=item.id, position_id=old.position_id,
                    rank=old.rank, similarity=old.similarity, approvable=old.approvable,
                    reasons_json=old.reasons_json, warnings_json=old.warnings_json
                ))
                total += 1
    run.candidate_count = total
    db.commit()
    return {"id": run.id, "parent_run_id": prior_run.id,
            "recomputed_item_count": len(changed), "copied_item_count": len(items) - len(changed),
            "row_count": len(items), "candidate_count": total,
            "previous_decisions_preserved_in_history": True,
            "previous_decisions_not_automatically_renewed": True}



@router.get("/projects/{project_id}/m21/run-history")
def list_match_history(project_id: str, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Older runs remain available; new decisions never rewrite prior runs."""
    project_or_404(db, project_id, user)
    runs = db.scalars(select(MatchRun).where(MatchRun.project_id == project_id)
                      .order_by(MatchRun.created_at.desc(), MatchRun.id.desc()).limit(100)).all()
    return [{"id": r.id, "import_id": r.import_id, "parent_run_id": r.parent_run_id,
             "algorithm": r.algorithm, "row_count": r.row_count,
             "candidate_count": r.candidate_count, "changed_item_count": r.changed_item_count,
             "created_at": r.created_at} for r in runs]


@router.get("/projects/{project_id}/m21/run-history/{run_id}")
def get_match_history(project_id: str, run_id: str, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Read-only evidence: frozen input, offered candidates and approval events."""
    project_or_404(db, project_id, user)
    run = db.scalar(select(MatchRun).where(MatchRun.project_id == project_id, MatchRun.id == run_id))
    if not run:
        raise HTTPException(404, "Matching run not found")
    from .models import MatchDecision
    rows = db.scalars(select(WorkItem).where(WorkItem.import_id == run.import_id)
                      .order_by(WorkItem.source_row)).all()
    snaps = {snap.work_item_id: snap for snap in db.scalars(select(MatchRunItemSnapshot)
             .where(MatchRunItemSnapshot.run_id == run.id)).all()}
    candidates = db.scalars(select(MatchCandidate).where(MatchCandidate.run_id == run.id)
                            .order_by(MatchCandidate.rank)).all()
    by_item = {}
    for candidate in candidates:
        pos = db.get(CatalogPosition, candidate.position_id)
        decisions = db.scalars(select(MatchDecision).where(
            MatchDecision.candidate_id == candidate.id).order_by(MatchDecision.created_at)).all()
        by_item.setdefault(candidate.work_item_id, []).append({
            "code": pos.code, "description": pos.description,
            "similarity": str(candidate.similarity), "approvable": candidate.approvable,
            "warnings": json.loads(candidate.warnings_json),
            "decisions": [{"action": d.action, "reason": d.reason, "decided_by": d.decided_by_id,
                           "at": d.created_at} for d in decisions]
        })
    return {"run_id": run.id, "import_id": run.import_id, "parent_run_id": run.parent_run_id,
            "created_at": run.created_at, "items": [
                {"work_item_id": item.id, "source_row": item.source_row,
                 "description": snaps[item.id].description if item.id in snaps else item.raw_description,
                 "quantity": str(snaps[item.id].quantity) if item.id in snaps and snaps[item.id].quantity is not None
                 else (str(item.quantity) if item.id not in snaps and item.quantity is not None else None),
                 "unit": snaps[item.id].unit if item.id in snaps else item.normalized_unit,
                 "review_required": snaps[item.id].review_required if item.id in snaps else item.review_required,
                 "candidates": by_item.get(item.id, [])} for item in rows]
    }
