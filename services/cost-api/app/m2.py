"""M2 matching HTTP routes.

Only a purpose-built synthetic catalog can be used in this pilot. Administrator
source attestations from M1 are NOT equivalent to independent commercial rights.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from .models import (
    User, Project, ImportBatch, WorkItem, CatalogSource, CatalogVersion, CatalogPosition,
    MatchRun, MatchCandidate, MatchDecision, MatchRunItemSnapshot, CatalogImport, BulkJob,
)
from .matching import ALGORITHM, MAX_MATCH_ROWS, find_candidates
from .revisions import effective_item, frozen_snapshot, previously_frozen, fingerprint
from .decision_reason import require_decision_reason

router = APIRouter(prefix="/api", tags=["M2 Matching"])
DEMO_INSTITUTION = "ARKEMX-SYNTHETIC-DEMO"
DEMO_SCOPE = "INTERNAL_DEMO_ONLY"
DEMO_VERSION = "2026-M2-SYNTHETIC"
DEMO_POSITIONS = (
    ("DEMO-SER-60", "60 x 60 porselen seramik zemin kaplaması", "m²"),
    ("DEMO-GAZ-10", "10 cm gazbeton duvar örülmesi", "m²"),
    ("DEMO-BETON", "Hazır beton dökümü yerinde uygulama", "m³"),
    ("DEMO-KAPI", "İç kapı montajı, adet", "adet"),
    ("DEMO-BOYA", "İç duvar yüzeyleri boya işleri", "m²"),
)


class RunRequest(BaseModel):
    use_local_ollama: bool = False


class DecisionRequest(BaseModel):
    run_id: str = Field(min_length=36, max_length=36)
    candidate_id: str = Field(min_length=36, max_length=36)
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


def tenant_project(db: Session, user: User, project_id: str) -> Project:
    project = db.scalar(select(Project).where(
        Project.id == project_id, Project.organization_id == user.organization_id
    ))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def synthetic_version(db: Session, org_id: str):
    source = db.scalar(select(CatalogSource).where(
        CatalogSource.organization_id == org_id,
        CatalogSource.institution == DEMO_INSTITUTION,
        CatalogSource.permission_scope == DEMO_SCOPE,
        CatalogSource.license_status == "verified",
    ))
    if source is None:
        raise HTTPException(409, "First create the synthetic test catalog")
    version = db.scalar(select(CatalogVersion).where(
        CatalogVersion.source_id == source.id, CatalogVersion.period == DEMO_VERSION
    ))
    if version is None:
        raise HTTPException(409, "Synthetic test catalog version missing")
    return version


@router.post("/m2/demo-catalog", status_code=201)
def seed_demo(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin required")
    source = db.scalar(select(CatalogSource).where(
        CatalogSource.organization_id == user.organization_id,
        CatalogSource.institution == DEMO_INSTITUTION,
        CatalogSource.permission_scope == DEMO_SCOPE,
    ))
    if source is None:
        source = CatalogSource(
            organization_id=user.organization_id, institution=DEMO_INSTITUTION,
            source_url=None, license_status="verified",
            permission_scope=DEMO_SCOPE,
            license_evidence="ARKEMX-generated fictional test records, not official prices",
            verified_by_id=user.id, verified_at=datetime.now(timezone.utc)
        )
        db.add(source)
        db.flush()
    version = db.scalar(select(CatalogVersion).where(
        CatalogVersion.source_id == source.id, CatalogVersion.period == DEMO_VERSION
    ))
    if version is None:
        canonical = json.dumps(DEMO_POSITIONS, ensure_ascii=False, separators=(",", ":"))
        version = CatalogVersion(
            source_id=source.id, year=2026, period=DEMO_VERSION,
            sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        )
        db.add(version)
        db.flush()
        for code, description, unit in DEMO_POSITIONS:
            db.add(CatalogPosition(version_id=version.id, code=code,
                                   description=description, unit=unit,
                                   price=None, currency="TRY"))
    db.commit()
    return {"version_id": version.id, "source": DEMO_INSTITUTION,
            "period": DEMO_VERSION, "synthetic": True, "position_count": len(DEMO_POSITIONS)}


@router.post("/projects/{project_id}/m2/run", status_code=201)
def generate_matches(project_id: str, payload: RunRequest, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    from .m43 import guard_no_active
    guard_no_active(db, project_id)
    version = synthetic_version(db, user.organization_id)
    # The exact marker prevents admin-attested/third-party catalogs from being
    # silently used without a separate operator licence gate.
    source = db.get(CatalogSource, version.source_id)
    if source is None or source.institution != DEMO_INSTITUTION or source.permission_scope != DEMO_SCOPE:
        raise HTTPException(403, "Unapproved catalog")
    batch = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                      .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    if not batch:
        raise HTTPException(409, "Import a quantity takeoff before matching")
    from .import_policy import guard_source
    guard_source(db, batch.id)
    if batch.row_count > MAX_MATCH_ROWS:
        raise HTTPException(422, f"M2 pilot can match at most {MAX_MATCH_ROWS} items per run")
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)
                       .order_by(WorkItem.source_row)).all()
    positions = db.scalars(select(CatalogPosition).where(CatalogPosition.version_id == version.id)
                           .order_by(CatalogPosition.code)).all()
    if not positions:
        raise HTTPException(409, "Catalog has no positions")
    ollama_enabled = payload.use_local_ollama and bool(os.getenv("M2_OLLAMA_MODEL", "").strip())
    run = MatchRun(
        project_id=project_id, import_id=batch.id, version_id=version.id, created_by_id=user.id,
        algorithm=ALGORITHM + ("+ollama-requested" if ollama_enabled else ""),
        row_count=len(items), candidate_count=0
    )
    db.add(run)
    db.flush()
    count = 0
    for item in items:
        current = effective_item(db, item)
        db.add(frozen_snapshot(run.id, current))
        candidates = find_candidates(current, positions, use_ollama=ollama_enabled)
        for index, entry in enumerate(candidates, start=1):
            db.add(MatchCandidate(
                run_id=run.id, work_item_id=item.id, position_id=entry["position_id"],
                rank=index, similarity=entry["similarity"], approvable=entry["approvable"],
                reasons_json=json.dumps(entry["reasons"], ensure_ascii=False),
                warnings_json=json.dumps(entry["warnings"], ensure_ascii=False)
            ))
            count += 1
    run.candidate_count = count
    db.commit()
    return {"id": run.id, "row_count": run.row_count, "candidate_count": count,
            "version_id": version.id, "mode": run.algorithm,
            "synthetic": True, "no_auto_approval": True}


def latest_run(db: Session, project_id: str):
    # M4.3 in-progress runs are not published or eligible for approval.
    done = select(BulkJob.run_id).where(BulkJob.status == "completed")
    return db.scalar(select(MatchRun).where(
        MatchRun.project_id == project_id,
        (MatchRun.algorithm != "technical-rules-v0.1+evidence-v0.1+bulk-v0.1") |
        MatchRun.id.in_(done)
    ).order_by(MatchRun.created_at.desc(), MatchRun.id.desc()))


@router.get("/projects/{project_id}/m2/latest")
def latest(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    run = latest_run(db, project_id)
    if run is None:
        return {"run": None, "items": []}
    version = db.get(CatalogVersion, run.version_id)
    source = db.get(CatalogSource, version.source_id)
    synthetic = source.institution == DEMO_INSTITUTION
    approved_import = None if synthetic else db.scalar(select(CatalogImport).where(
        CatalogImport.organization_id == user.organization_id,
        CatalogImport.version_id == run.version_id,
        CatalogImport.status == "approved",
        CatalogImport.approval_scope == "internal_matching"))
    rights_active = synthetic or bool(approved_import and approved_import.approval_evidence and approved_import.reviewed_by)
    candidates = db.scalars(select(MatchCandidate).where(MatchCandidate.run_id == run.id)
                            .order_by(MatchCandidate.rank)).all()
    by_item = {}
    for candidate in candidates:
        pos = db.get(CatalogPosition, candidate.position_id)
        by_item.setdefault(candidate.work_item_id, []).append({
            "id": candidate.id, "rank": candidate.rank, "position_id": pos.id,
            "code": pos.code, "description": pos.description, "unit": pos.unit,
            "similarity": float(candidate.similarity),
            "reasons": json.loads(candidate.reasons_json),
            "warnings": json.loads(candidate.warnings_json),
            "approvable": candidate.approvable,
        })
    decisions = db.scalars(select(MatchDecision).join(MatchCandidate)
                           .where(MatchCandidate.run_id == run.id)
                           .order_by(MatchDecision.created_at, MatchDecision.id)).all()
    last_decision = {}
    for d in decisions:
        candidate = db.get(MatchCandidate, d.candidate_id)
        last_decision[candidate.work_item_id] = {
            "action": d.action, "candidate_id": d.candidate_id,
            "reason": d.reason, "decided_by": d.decided_by_id, "at": d.created_at,
        }
    # Old M2 runs have no frozen snapshots. They retain their original upload values.
    frozen = {s.work_item_id: s for s in db.scalars(select(MatchRunItemSnapshot)
              .where(MatchRunItemSnapshot.run_id == run.id)).all()}
    rows = db.scalars(select(WorkItem).where(WorkItem.import_id == run.import_id)
                      .order_by(WorkItem.source_row)).all()
    current_import = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                    .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    from .import_policy import source_excluded
    outdated_import = (not current_import or current_import.id != run.import_id
                       or source_excluded(db, current_import.id if current_import else None))
    return {
        "run": {"id": run.id, "algorithm": run.algorithm, "row_count": run.row_count,
                "candidate_count": run.candidate_count, "created_at": run.created_at,
                "catalog_period": version.period, "source": source.institution,
                "synthetic": synthetic, "rights_active": rights_active,
                "catalog_year": version.year, "catalog_sha256": version.sha256,
                "scores_are_probabilities": False,
                "parent_run_id": run.parent_run_id,
                "changed_item_count": run.changed_item_count,
                "outdated_import": outdated_import},
        "items": [{"id": item.id, "source_row": item.source_row,
                   "description": frozen[item.id].description if item.id in frozen else item.raw_description,
                   "quantity": str(frozen[item.id].quantity) if item.id in frozen and frozen[item.id].quantity is not None else (str(item.quantity) if item.id not in frozen and item.quantity is not None else None),
                   "unit": frozen[item.id].unit if item.id in frozen else item.normalized_unit,
                   "review_required": frozen[item.id].review_required if item.id in frozen else item.review_required,
                   "stale": (not rights_active) or outdated_import or fingerprint(effective_item(db, item)) != previously_frozen(item, frozen.get(item.id)),
                   "candidates": by_item.get(item.id, []),
                   "decision": last_decision.get(item.id)} for item in rows]
    }


@router.post("/projects/{project_id}/m2/decisions", status_code=201)
def decide(project_id: str, payload: DecisionRequest, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    run = latest_run(db, project_id)
    if run is None or run.id != payload.run_id:
        raise HTTPException(409, "Decision must refer to the latest matching run")
    candidate = db.scalar(select(MatchCandidate).where(
        MatchCandidate.id == payload.candidate_id, MatchCandidate.run_id == run.id))
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    item = db.get(WorkItem, candidate.work_item_id)
    recorded_identity_proof = None
    # M4 reports are immutable evidence. A new approval must pass its original
    # technical gate; historical M2/M3 decisions are not rewritten.
    if payload.action == "approve" and run.algorithm in (
        "technical-rules-v0.1", "technical-rules-v0.1+evidence-v0.1",
        "technical-rules-v0.1+evidence-v0.1+bulk-v0.1"):
        from .models import TechnicalComparison
        report = db.scalar(select(TechnicalComparison).where(
            TechnicalComparison.candidate_id == candidate.id))
        if report is None or report.status != "compatible":
            raise HTTPException(409, "Technical comparison blocks approval; inspect M4 report")
        if run.algorithm in ("technical-rules-v0.1+evidence-v0.1",
                             "technical-rules-v0.1+evidence-v0.1+bulk-v0.1"):
            from .models import TechnicalEvidence
            from .evidence_v41 import verify_evidence
            evidence = db.scalar(select(TechnicalEvidence).where(
                TechnicalEvidence.candidate_id == candidate.id))
            if evidence is None or evidence.status != "compatible":
                raise HTTPException(409, "Verified technical evidence required")
            try:
                evidence_payload = json.loads(evidence.payload_json)
            except (ValueError, TypeError):
                raise HTTPException(409, "Invalid evidence payload") from None
            if not verify_evidence(evidence_payload) or evidence_payload.get("evidence_sha256") != evidence.evidence_sha256:
                raise HTTPException(409, "Technical evidence integrity failed")
            recorded_identity_proof = evidence_payload
    version = db.get(CatalogVersion, run.version_id)
    source = db.get(CatalogSource, version.source_id)
    if payload.action == "approve" and source.institution != DEMO_INSTITUTION:
        from .m3 import eligible_version
        eligible_version(db, user.organization_id, run.version_id)
    current_import = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                    .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    snapshot = db.scalar(select(MatchRunItemSnapshot).where(
        MatchRunItemSnapshot.run_id == run.id, MatchRunItemSnapshot.work_item_id == item.id))
    from .import_policy import source_excluded
    stale = (not current_import or current_import.id != run.import_id
             or source_excluded(db, current_import.id if current_import else None)
             or (fingerprint(effective_item(db, item)) != previously_frozen(item, snapshot)))
    if payload.action == "approve" and stale:
        raise HTTPException(409, "Metraj changed after this run; recompute before approval")
    if payload.action == "approve":
        from .identity_guard import approval_identity_issue
        position = db.get(CatalogPosition, candidate.position_id)
        issue = approval_identity_issue(snapshot.description if snapshot else item.raw_description,
                                        position.description, position.code, recorded_identity_proof)
        if issue:
            raise HTTPException(409, "Position identity not verified: " + issue)
    if payload.action == "approve" and (not candidate.approvable or (snapshot.review_required if snapshot else item.review_required)):
        raise HTTPException(409, "Candidate has unresolved technical or metraj warnings")
    # M4.2 technical-evidence decisions require meaningful rationale.
    # Original M2/M3 synthetic pilot allowed an optional rationale; preserve its
    # API contract and run legacy permission/staleness gates before text checks.
    evidence_run = run.algorithm in (
        "technical-rules-v0.1+evidence-v0.1",
        "technical-rules-v0.1+evidence-v0.1+bulk-v0.1",
    )
    clean_reason = (require_decision_reason(payload.reason)
                    if evidence_run and (payload.action == "approve" or payload.reason is not None)
                    else payload.reason)
    db.add(MatchDecision(candidate_id=candidate.id, action=payload.action,
                         decided_by_id=user.id, reason=clean_reason))
    db.commit()
    return {"candidate_id": candidate.id, "action": payload.action,
            "approved_automatically": False}
