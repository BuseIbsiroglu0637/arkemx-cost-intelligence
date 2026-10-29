"""A3.9.2 - Tenant-scoped, non-persistent review of selected imported rows."""

import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import ImportBatch, MetrajImportExclusion, Project, User, WorkItem
from .revisions import effective_item, latest_revision
from .security import current_user
from .technical_analysis.batch_technical_review import (
    review_rows,
    row_from_effective_item,
)

router = APIRouter(prefix="/api/projects/{project_id}/a3", tags=["A3 Batch Review"])
NO_STORE = {"Cache-Control": "private, no-store"}


class SelectedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_id: UUID
    candidate_code: str | None = Field(default=None, min_length=1, max_length=80)
    expected_revision_id: UUID | None = None


class BatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[SelectedRow] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def reject_duplicate_items(self):
        ids = [row.work_item_id for row in self.rows]
        if len(set(ids)) != len(ids):
            raise ValueError("Each work item can be selected only once")
        return self


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail, headers=NO_STORE)


def _source(db: Session, user: User, project_id: str, import_id: str) -> ImportBatch:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.organization_id == user.organization_id,
        )
    )
    if project is None:
        raise _error(404, "Project or import not found")
    batch = db.scalar(
        select(ImportBatch).where(
            ImportBatch.id == import_id,
            ImportBatch.project_id == project.id,
        )
    )
    if batch is None:
        raise _error(404, "Project or import not found")
    if db.get(MetrajImportExclusion, batch.id) is not None:
        raise _error(409, "Selected Excel import is excluded from new analysis")
    return batch


def _source_view(batch: ImportBatch) -> dict:
    return {
        "import_id": batch.id,
        "project_id": batch.project_id,
        "filename": batch.original_filename,
        "sha256": batch.sha256,
        "sheet_name": batch.sheet_name,
        "row_count": batch.row_count,
    }


@router.get("/imports/{import_id}/items")
def selectable_rows(
    project_id: UUID,
    import_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
):
    batch = _source(db, user, str(project_id), str(import_id))
    items = db.scalars(
        select(WorkItem)
        .where(WorkItem.import_id == batch.id)
        .order_by(WorkItem.source_row, WorkItem.id)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    visible = items[:limit]
    rows = []
    for item in visible:
        current = effective_item(db, item)
        rows.append(
            {
                "work_item_id": item.id,
                "source_row": item.source_row,
                "original_description": item.raw_description,
                "effective_description": current.raw_description,
                "quantity": str(current.quantity)
                if current.quantity is not None
                else None,
                "unit": current.normalized_unit,
                "revision_id": current.revision_id,
                "input_review_required": current.review_required,
            }
        )
    response.headers.update(NO_STORE)
    return {
        "schema": "arkemx.batch_review_selection.v1",
        "read_only": True,
        "approval_allowed": False,
        "import_source": _source_view(batch),
        "rows": rows,
        "next_offset": offset + limit if len(items) > limit else None,
    }


@router.post("/imports/{import_id}/technical-review")
def preview_batch_review(
    project_id: UUID,
    import_id: UUID,
    payload: BatchReviewRequest,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    ids = [str(row.work_item_id) for row in payload.rows]
    items = db.scalars(
        select(WorkItem).where(
            WorkItem.import_id == batch.id,
            WorkItem.id.in_(ids),
        )
    ).all()
    by_id = {item.id: item for item in items}
    if set(by_id) != set(ids):
        raise _error(404, "Selected row not found in this import")
    prepared = []
    for selection in payload.rows:
        item = by_id[str(selection.work_item_id)]
        revision = latest_revision(db, item.id)
        actual_revision = revision.id if revision else None
        expected = (
            str(selection.expected_revision_id)
            if selection.expected_revision_id
            else None
        )
        if expected != actual_revision:
            raise _error(409, "Metraj revision changed; reload rows before reviewing")
        current = effective_item(db, item, revision)
        prepared.append(
            row_from_effective_item(
                item,
                current,
                sheet_name=batch.sheet_name,
                candidate_code=selection.candidate_code,
            )
        )
    try:
        result = review_rows(
            tuple(prepared), pdf_path=os.environ.get("ARKEMX_ANALYSIS_PDF")
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise _error(422, "Selected source rows could not be validated") from exc
    if (
        result.get("approval_allowed") is not False
        or result.get("read_only") is not True
    ):
        raise _error(500, "Batch preview cannot authorize approval")
    result["import_source"] = _source_view(batch)
    response.headers.update(NO_STORE)
    return result
