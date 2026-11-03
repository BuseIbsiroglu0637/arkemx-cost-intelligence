"""A3.50.1 — read-only classification diagnostics, grounded in saved sources.

The report measures taxonomy coverage, NOT poz-matching correctness. It does
not create a classification database, overwrite user metraj, or approve cost.
"""
from __future__ import annotations

from collections import Counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source as import_source
from .a348_catalog_library_api import _source as price_source
from .a350_work_taxonomy import TAXONOMY_VERSION, classify_work
from .database import get_db
from .models import User, WorkItem
from .revisions import effective_item
from .security import current_user

catalog_router = APIRouter(prefix="/api/a350/catalog", tags=["A3.50.1 Catalog Work Classification"])
metraj_router = APIRouter(prefix="/api/projects/{project_id}/a350", tags=["A3.50.1 Metraj Work Classification"])


def _stats(entries: list[dict]) -> dict:
    return {
        "classified_count": sum(x["status"] == "classified" for x in entries),
        "review_count": sum(x["status"] != "classified" for x in entries),
        "by_class": dict(sorted(Counter(x["class_key"] for x in entries).items())),
        "by_status": dict(sorted(Counter(x["status"] for x in entries).items())),
        "by_source_role": dict(sorted(Counter(x["source_role"] for x in entries).items())),
    }


@catalog_router.get("/classification")
def catalog_classification_report(
    response: Response,
    user: Annotated[User, Depends(current_user)],
):
    pdf = price_source(user)
    if pdf is None:
        raise HTTPException(409, "Verified 2026 PDF catalog is not installed", headers=NO_STORE)
    analyses = []
    unclassified_examples = []
    for row in pdf["records"]:
        work = classify_work(row["description"], catalog_kind=row["kind"])
        analyses.append(work)
        if work["status"] != "classified" and len(unclassified_examples) < 15:
            unclassified_examples.append({
                "code": row["code"],
                "description": row["description"],
                "pdf_page": row["pdf_page"],
                "class_key": work["class_key"],
                "review_reasons": work["review_reasons"],
            })
    response.headers.update(NO_STORE)
    return {
        "version": TAXONOMY_VERSION,
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "matching_performed": False,
        "source": {
            "source_sha256": pdf["source_sha256"],
            "edition_date": pdf["edition_date"],
            "kind": "official_pdf_price_list",
        },
        "total_records": len(analyses),
        "summary": _stats(analyses),
        "unclassified_examples": unclassified_examples,
    }


@metraj_router.get("/imports/{import_id}/classification")
def metraj_classification_report(
    project_id: UUID, import_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    batch = import_source(db, user, str(project_id), str(import_id))
    # All rows are inspected for a *complete* coverage denominator, not just
    # the current page. The original import rows are never modified.
    originals = db.scalars(
        select(WorkItem)
        .where(WorkItem.import_id == batch.id)
        .order_by(WorkItem.source_row, WorkItem.id)
    ).all()
    classified = []
    for original in originals:
        current = effective_item(db, original)
        work = classify_work(current.raw_description)
        classified.append({
            "work_item_id": original.id,
            "source_row": original.source_row,
            "description": current.raw_description,
            "unit": current.normalized_unit,
            "revision_id": current.revision_id,
            "work_class": work,
        })
    response.headers.update(NO_STORE)
    return {
        "version": TAXONOMY_VERSION,
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "matching_performed": False,
        "source": {
            "project_id": batch.project_id,
            "import_id": batch.id,
            "excel_sha256": batch.sha256,
            "sheet_name": batch.sheet_name,
        },
        "total_rows": len(originals),
        "summary": _stats([row["work_class"] for row in classified]),
        "offset": offset,
        "returned": len(classified[offset:offset + limit]),
        "has_more": offset + limit < len(classified),
        "rows": classified[offset:offset + limit],
    }
