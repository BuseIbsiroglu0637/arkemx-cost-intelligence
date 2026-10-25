"""M4.1 source-attributed evidence routes; no mutation to existing M4 runs."""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from .models import User, TechnicalEvidence
from .m2 import tenant_project, latest as latest_m2
from .m4 import _build_run
from .evidence_v41 import ALGORITHM, verify_evidence

router = APIRouter(prefix="/api", tags=["M4.1 Technical Evidence"])


@router.post("/projects/{project_id}/m41/run", status_code=201)
def run_evidence(project_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    return _build_run(project_id, user, db, with_evidence=True)


@router.get("/projects/{project_id}/m41/latest")
def latest_evidence(project_id: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    payload = latest_m2(project_id, user, db)
    if not payload.get("run") or payload["run"]["algorithm"] != ALGORITHM:
        return {"run": None, "items": [], "message": "No M4.1 evidence run yet"}
    candidate_ids = [c["id"] for item in payload["items"] for c in item["candidates"]]
    evidence_rows = db.scalars(select(TechnicalEvidence).where(
        TechnicalEvidence.candidate_id.in_(candidate_ids))).all() if candidate_ids else []
    by_id = {}
    for entry in evidence_rows:
        try:
            parsed = json.loads(entry.payload_json)
        except (ValueError, TypeError):
            raise HTTPException(409, "Recorded evidence is malformed") from None
        if (not verify_evidence(parsed) or entry.evidence_sha256 != parsed.get("evidence_sha256")
                or entry.status != parsed.get("status") or entry.schema_version != parsed.get("schema")):
            raise HTTPException(409, "Recorded evidence integrity mismatch")
        by_id[entry.candidate_id] = parsed
    for item in payload["items"]:
        for candidate in item["candidates"]:
            candidate["evidence"] = by_id.get(candidate["id"])
            # Missing evidence cannot be presented as verified/approvable.
            if candidate["evidence"] is None:
                candidate["approvable"] = False
    return payload
