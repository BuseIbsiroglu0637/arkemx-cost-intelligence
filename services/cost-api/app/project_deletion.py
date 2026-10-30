"""Explicit tenant-scoped project deletion with dependent-record and upload cleanup.

A deletion is irreversible. No destructive endpoint is exposed without admin
authorization and an exact project-name + project-ID confirmation.
"""
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import BulkJob, ImportBatch, MatchRun, Project, User
from .security import current_user

router = APIRouter(prefix="/api/projects", tags=["Project management"])


class DeleteProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_project_id: str
    confirm_name: str


def dependent_rows(db: Session, project_id: str, organization_id: str) -> dict[str, set]:
    """Follow child foreign keys from THIS project, never shared catalogs/users.

    Tables must have single-column primary keys; unknown schemas fail closed.
    """
    tables = list(Base.metadata.sorted_tables)
    selected: dict[str, set] = {"projects": {project_id}}

    for _ in range(len(tables) + 1):
        updated = False
        for table in tables:
            if table.name == "projects":
                continue
            parents = [
                column.in_(selected[fk.column.table.name])
                for column in table.columns
                for fk in column.foreign_keys
                if selected.get(fk.column.table.name)
            ]
            if not parents:
                continue
            # A malformed cross-project foreign key must never pull another
            # tenant's or another project's root-scoped data into a deletion.
            if "project_id" in table.c:
                parents.append(table.c.project_id == project_id)
                predicate = (or_(*parents[:-1])) & parents[-1]
            else:
                predicate = or_(*parents)
            if "organization_id" in table.c:
                predicate = predicate & (table.c.organization_id == organization_id)
            primary = list(table.primary_key.columns)
            if len(primary) != 1:
                raise RuntimeError("Unrecognized project dependency schema")
            found = set(db.scalars(select(primary[0]).where(predicate)).all())
            if not found.issubset(selected.get(table.name, set())):
                selected.setdefault(table.name, set()).update(found)
                updated = True
        if not updated:
            return selected
    raise RuntimeError("Project dependency cycle could not be resolved")


def upload_paths(project: Project, keys: list[str]) -> tuple[Path, list[Path]]:
    """Validate all stored paths before any mutation, without following symlinks."""
    root = Path(os.environ.get("UPLOAD_DIR", "./data/uploads")).resolve()
    result = []
    for key in keys:
        relative = Path(key)
        segments = relative.parts
        if (
            len(segments) != 3
            or segments[0] != project.organization_id
            or segments[1] != project.id
            or not segments[2].endswith(".xlsx")
            or relative.is_absolute()
            or "\\" in key
        ):
            raise ValueError("Unexpected project upload key")
        candidate = (root / key).resolve()
        if not candidate.is_relative_to(root) or candidate.suffix.lower() != ".xlsx":
            raise ValueError("Unsafe project upload path")
        result.append(candidate)
    return root, result


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    payload: DeleteProjectRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(403, "Administrator required")

    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.organization_id == user.organization_id)
        .with_for_update()
    )
    if project is None:
        raise HTTPException(404, "Project not found")
    if payload.confirm_project_id != project.id or payload.confirm_name != project.name:
        raise HTTPException(409, "Project confirmation does not match")

    active = db.scalar(
        select(BulkJob.id).where(
            BulkJob.project_id == project_id,
            BulkJob.status.in_(("queued", "running")),
        ).limit(1)
    )
    if active:
        raise HTTPException(409, "Stop the active batch operation before deleting")

    owned = dependent_rows(db, project.id, user.organization_id)
    import_ids = owned.get("imports", set())
    keys = list(db.scalars(
        select(ImportBatch.stored_key).where(ImportBatch.id.in_(import_ids))
    ).all()) if import_ids else []

    try:
        root, sources = upload_paths(project, keys)
    except ValueError as exc:
        raise HTTPException(409, "Project upload paths require operator review") from exc

    # Quarantine files before the DB commit. A failed DB transaction restores
    # them; successful deletion removes the quarantined copies afterward.
    quarantine = root / ".project-deletion" / uuid4().hex
    moved: list[tuple[Path, Path]] = []
    committed = False
    try:
        for source in sources:
            if not source.exists():
                continue
            relative = source.relative_to(root)
            held = quarantine / relative
            held.parent.mkdir(parents=True, exist_ok=True)
            source.replace(held)
            moved.append((source, held))

        run_ids = owned.get("match_runs", set())
        if run_ids:
            db.execute(
                update(MatchRun)
                .where(MatchRun.id.in_(run_ids))
                .values(parent_run_id=None)
            )

        # Children first; the organization, users and shared catalog
        # versions have no parent path from a project and remain untouched.
        for table in reversed(Base.metadata.sorted_tables):
            ids = owned.get(table.name)
            if ids:
                primary = list(table.primary_key.columns)
                if len(primary) != 1:
                    raise RuntimeError("Unexpected primary-key schema")
                db.execute(delete(table).where(primary[0].in_(ids)))
        db.commit()
        committed = True
    except Exception:
        db.rollback()
        for source, held in reversed(moved):
            if held.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                held.replace(source)
        raise
    finally:
        if not committed and quarantine.exists():
            shutil.rmtree(quarantine, ignore_errors=True)

    cleanup_pending = False
    if quarantine.exists():
        try:
            shutil.rmtree(quarantine)
        except OSError:
            cleanup_pending = True

    return {
        "deleted_project_id": project_id,
        "deleted_import_count": len(import_ids),
        "cleanup_pending": cleanup_pending,
    }
