"""M3 rights-gated, multi-institution catalog staging and matching.

Uploads are NOT public information retrieval. No catalog becomes matchable
until a separate *local operator* records a reviewed evidence trail via CLI.
"""
import json
import os
import re
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from .models import (User, CatalogSource, CatalogVersion, CatalogPosition, CatalogImport,
                     Project, ImportBatch, WorkItem, MatchRun, MatchCandidate)
from .catalog_parser import CatalogError, parse_catalog, inspect_catalog, MAX_CATALOG_BYTES
from .matching import ALGORITHM, find_candidates, MAX_MATCH_ROWS
from .revisions import effective_item, frozen_snapshot

router = APIRouter(prefix="/api/m3", tags=["M3 Catalog Rights & Imports"])
INSTITUTIONS = {"CSB": "ÇŞİDB", "DSI": "DSİ", "KGM": "KGM", "ILBANK": "İLBANK", "OTHER": "Diğer"}
SCOPE = "internal_matching"


class RunRequest(BaseModel):
    version_id: str
    use_local_ollama: bool = False


def require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(403, "Organization administrator required")


async def file_bytes(file: UploadFile):
    name = file.filename or ""
    if not name.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(415, "Only XLSX or CSV")
    content = await file.read(MAX_CATALOG_BYTES + 1)
    await file.close()
    if len(content) > MAX_CATALOG_BYTES:
        raise HTTPException(413, "Maximum 5 MB")
    return name, content


def load_mapping(raw: str | None):
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
            raise ValueError()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(422, "columns must be a JSON object of field-to-header names") from None
    return data


def parse_or_422(name, content, columns):
    try:
        return parse_catalog(name, content, load_mapping(columns))
    except CatalogError as exc:
        raise HTTPException(422, str(exc)) from exc


def dataset_view(imp, source, version):
    return {
        "id": imp.id, "version_id": imp.version_id, "source_id": imp.source_id,
        "institution": source.institution, "source_url": source.source_url,
        "year": imp.year, "period": imp.period, "row_count": imp.row_count,
        "sha256": imp.sha256, "filename": imp.filename, "status": imp.status,
        "approved": imp.status == "approved" and imp.approval_scope == SCOPE
                    and bool(imp.approval_evidence and imp.reviewed_by),
        "approval_scope": imp.approval_scope, "reviewed_by": imp.reviewed_by,
        "reviewed_at": imp.reviewed_at, "created_at": imp.created_at,
    }


@router.post("/inspect")
async def inspect(file: UploadFile = File(...), user: User = Depends(current_user)):
    require_admin(user)
    name, data = await file_bytes(file)
    try:
        return inspect_catalog(name, data)
    except CatalogError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/preview")
async def preview(file: UploadFile = File(...), columns: str | None = Form(None),
                  user: User = Depends(current_user)):
    require_admin(user)
    name, data = await file_bytes(file)
    parsed = parse_or_422(name, data, columns)
    return {k: v for k, v in parsed.items() if k != "rows"} | {
        "preview": parsed["rows"][:12], "status": "preview_only", "persisted": False,
    }


@router.post("/imports", status_code=201)
async def stage_catalog(
    file: UploadFile = File(...),
    institution: Literal["CSB", "DSI", "KGM", "ILBANK", "OTHER"] = Form(...),
    year: int = Form(..., ge=2000, le=2100),
    period: str = Form(..., min_length=1, max_length=40),
    source_url: str | None = Form(None),
    columns: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    if period.strip() != period or not period.strip():
        raise HTTPException(422, "Invalid period")
    if source_url:
        if len(source_url) > 1000 or not re.match(r"^https://[^/\s]+(?:/.*)?$", source_url):
            raise HTTPException(422, "Only HTTPS source references are accepted")
    name, data = await file_bytes(file)
    parsed = parse_or_422(name, data, columns)
    digest = parsed["sha256"]
    # Scope version+hash to organization; no user can import another tenant's IDs.
    existing = db.scalar(select(CatalogImport).where(
        CatalogImport.organization_id == user.organization_id,
        CatalogImport.sha256 == digest, CatalogImport.year == year,
        CatalogImport.period == period).join(CatalogSource, CatalogSource.id == CatalogImport.source_id)
        .where(CatalogSource.institution == institution))
    if existing:
        raise HTTPException(409, "This exact catalog file/year/period was already imported")
    source = db.scalar(select(CatalogSource).where(
        CatalogSource.organization_id == user.organization_id,
        CatalogSource.institution == institution,
        CatalogSource.source_url == source_url))
    if source is None:
        source = CatalogSource(organization_id=user.organization_id,
                               institution=institution, source_url=source_url,
                               license_status="pending")
        db.add(source)
        db.flush()
    version = CatalogVersion(source_id=source.id, year=year, period=period, sha256=digest)
    db.add(version)
    db.flush()
    for entry in parsed["rows"]:
        db.add(CatalogPosition(version_id=version.id, code=entry["code"],
                               description=entry["description"], unit=entry["unit"],
                               price=entry["price"], currency="TRY"))
    imp = CatalogImport(
        organization_id=user.organization_id, source_id=source.id, version_id=version.id,
        sha256=digest, filename=Path(name.replace("\\", "/")).name[:255], year=year,
        period=period, row_count=parsed["row_count"], status="pending", created_by_id=user.id)
    db.add(imp)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate catalog import") from None
    return dataset_view(imp, source, version)


@router.get("/imports")
def list_imports(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(CatalogImport).where(
        CatalogImport.organization_id == user.organization_id
    ).order_by(CatalogImport.created_at.desc(), CatalogImport.id.desc())).all()
    return [dataset_view(i, db.get(CatalogSource, i.source_id),
                         db.get(CatalogVersion, i.version_id)) for i in rows]


@router.get("/imports/{import_id}/positions")
def sample_positions(import_id: str, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    imp = db.scalar(select(CatalogImport).where(
        CatalogImport.id == import_id,
        CatalogImport.organization_id == user.organization_id))
    if not imp:
        raise HTTPException(404, "Catalog import not found")
    positions = db.scalars(select(CatalogPosition).where(
        CatalogPosition.version_id == imp.version_id
    ).order_by(CatalogPosition.code).limit(20)).all()
    return {"import_id": imp.id, "status": imp.status,
            "positions": [{"code": p.code, "description": p.description, "unit": p.unit,
                           "price": str(p.price) if p.price is not None else None}
                          for p in positions]}


def eligible_version(db: Session, org_id: str, version_id: str):
    imp = db.scalar(select(CatalogImport).where(
        CatalogImport.version_id == version_id,
        CatalogImport.organization_id == org_id,
        CatalogImport.status == "approved",
        CatalogImport.approval_scope == SCOPE,
        CatalogImport.approval_evidence.is_not(None),
        CatalogImport.reviewed_by.is_not(None)))
    if not imp or not imp.approval_evidence.strip() or not imp.reviewed_by.strip():
        raise HTTPException(403, "Catalog has no independent operator rights approval")
    version = db.get(CatalogVersion, imp.version_id)
    if not version or version.sha256 != imp.sha256:
        raise HTTPException(409, "Catalog version hash mismatch")
    return imp, version


@router.post("/projects/{project_id}/run", status_code=201)
def run_real_catalog(project_id: str, payload: RunRequest,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = db.scalar(select(Project).where(
        Project.id == project_id, Project.organization_id == user.organization_id))
    if not project:
        raise HTTPException(404, "Project not found")
    imp, version = eligible_version(db, user.organization_id, payload.version_id)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                      .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))
    if batch is None:
        raise HTTPException(409, "Import metraj before matching")
    if batch.row_count > MAX_MATCH_ROWS:
        raise HTTPException(422, f"Pilot supports up to {MAX_MATCH_ROWS} metraj rows")
    positions = db.scalars(select(CatalogPosition).where(
        CatalogPosition.version_id == version.id).order_by(CatalogPosition.code)).all()
    if not positions:
        raise HTTPException(409, "Catalog is empty")
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)
                       .order_by(WorkItem.source_row)).all()
    enabled = payload.use_local_ollama and bool(os.getenv("M2_OLLAMA_MODEL", "").strip())
    run = MatchRun(project_id=project_id, import_id=batch.id, version_id=version.id,
                   created_by_id=user.id, algorithm=ALGORITHM +
                   ("+ollama-requested" if enabled else "") + "+rights-reviewed",
                   row_count=len(items), candidate_count=0)
    db.add(run)
    db.flush()
    for item in items:
        effective = effective_item(db, item)
        db.add(frozen_snapshot(run.id, effective))
        for rank, result in enumerate(find_candidates(effective, positions, use_ollama=enabled), 1):
            db.add(MatchCandidate(
                run_id=run.id, work_item_id=item.id, position_id=result["position_id"],
                rank=rank, similarity=result["similarity"],
                reasons_json=json.dumps(result["reasons"], ensure_ascii=False),
                warnings_json=json.dumps(result["warnings"], ensure_ascii=False),
                approvable=result["approvable"]))
            run.candidate_count += 1
    db.commit()
    return {"id": run.id, "version_id": version.id, "source": imp.id,
            "catalog_status": "operator_reviewed", "candidate_count": run.candidate_count,
            "row_count": run.row_count, "human_approval_required": True}
