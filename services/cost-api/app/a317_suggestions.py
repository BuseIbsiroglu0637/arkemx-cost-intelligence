"""A3.17: read-only candidate discovery for a selected, authorized Excel source.

Lexical candidates are suggestions, never verified engineering decisions.
No pricing, approval, DB mutation or background jobs occur in this endpoint.
"""
from collections import Counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source, _source_view
from .database import get_db
from .m2 import DEMO_INSTITUTION, DEMO_SCOPE, tenant_project
from .m43 import _rights
from .m43_worker import POSITION_LIMIT
from .matching import find_candidates
from .models import (
    CatalogImport,
    CatalogPosition,
    CatalogSource,
    CatalogVersion,
    ImportBatch,
    User,
    WorkItem,
)
from .revisions import effective_item
from .security import current_user
from .technical import compare

router = APIRouter(prefix="/api/projects/{project_id}/a317", tags=["A3.17 Candidate Suggestions"])
MAX_ROWS = 20


@router.get("/catalogs")
def catalogs(
    project_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    tenant_project(db, user, str(project_id))
    response.headers.update(NO_STORE)
    catalog_imports = db.scalars(select(CatalogImport).where(
        CatalogImport.organization_id == user.organization_id,
        CatalogImport.status == "approved",
        CatalogImport.approval_scope == "internal_matching",
    )).all()
    versions = {row.version_id for row in catalog_imports}
    synthetic = db.scalar(select(CatalogSource).where(
        CatalogSource.organization_id == user.organization_id,
        CatalogSource.institution == DEMO_INSTITUTION,
        CatalogSource.permission_scope == DEMO_SCOPE,
        CatalogSource.license_status == "verified",
    ))
    if synthetic:
        versions.update(db.scalars(select(CatalogVersion.id).where(
            CatalogVersion.source_id == synthetic.id,
            CatalogVersion.period == "2026-M2-SYNTHETIC",
        )).all())
    output = []
    for version_id in sorted(versions):
        try:
            version, origin = _rights(db, user, version_id)
        except HTTPException:
            continue
        count = db.scalar(select(func.count(CatalogPosition.id)).where(
            CatalogPosition.version_id == version.id,
        )) or 0
        if 1 <= count <= POSITION_LIMIT:
            output.append({
                "version_id": version.id, "institution": origin.institution,
                "year": version.year, "period": version.period,
                "position_count": count,
                "synthetic": origin.institution == DEMO_INSTITUTION,
            })
    return {"read_only": True, "catalogs": output}


@router.get("/imports/{import_id}/suggestions")
def suggest(
    project_id: UUID,
    import_id: UUID,
    version_id: Annotated[UUID, Query()],
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
):
    batch: ImportBatch = _source(db, user, str(project_id), str(import_id))
    version, origin = _rights(db, user, str(version_id))
    positions = db.scalars(select(CatalogPosition).where(
        CatalogPosition.version_id == version.id,
    ).order_by(CatalogPosition.code, CatalogPosition.id).limit(POSITION_LIMIT + 1)).all()
    if not positions or len(positions) > POSITION_LIMIT:
        raise HTTPException(409, "Catalog size is outside the pilot limit", headers=NO_STORE)

    items = db.scalars(select(WorkItem).where(
        WorkItem.import_id == batch.id,
    ).order_by(WorkItem.source_row, WorkItem.id).offset(offset).limit(MAX_ROWS)).all()
    rows = []
    for item in items:
        current = effective_item(db, item)
        by_position = {position.id: position for position in positions}
        shortlist = find_candidates(current, positions)
        suggestions = []
        for candidate in shortlist:
            pos = by_position[candidate["position_id"]]
            technical = compare(
                current.raw_description, current.normalized_unit,
                pos.description, pos.unit,
                quantity_known=current.quantity is not None,
                review_required=current.review_required,
            )
            suggestions.append({
                "code": pos.code,
                "description": pos.description,
                "unit": pos.unit,
                "similarity": candidate["similarity"],
                "technical_status": technical["status"],
                "blockers": technical["blockers"],
                "review_flags": technical["review_flags"],
                "source_version_id": version.id,
            })
        suggestions.sort(key=lambda v: (
            {"compatible": 0, "review": 1, "blocked": 2}[v["technical_status"]],
            -v["similarity"], v["code"],
        ))
        rows.append({
            "work_item_id": item.id, "source_row": item.source_row,
            "revision_id": current.revision_id,
            "suggestions": suggestions,
        })
    # A shared top-choice poz may cover multiple metraj rows (e.g. two
    # plaster layers). Do NOT silently assign the same candidate to both.
    proposed = Counter(
        row["suggestions"][0]["code"]
        for row in rows if row["suggestions"]
        and row["suggestions"][0]["technical_status"] != "blocked"
    )
    for row in rows:
        for candidate in row["suggestions"]:
            candidate["possible_shared_scope"] = proposed[candidate["code"]] > 1

    response.headers.update(NO_STORE)
    return {
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "import_source": _source_view(batch),
        "catalog": {
            "version_id": version.id, "institution": origin.institution,
            "year": version.year, "period": version.period,
            "sha256": version.sha256,
            "synthetic": origin.institution == DEMO_INSTITUTION,
        },
        "rows": rows,
        "page_offset": offset,
    }
