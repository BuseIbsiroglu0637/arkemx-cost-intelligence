"""Immutable quantity takeoff correction helpers (M2.1)."""
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import WorkItem, WorkItemRevision, MatchRunItemSnapshot


def latest_revision(db: Session, work_item_id: str) -> WorkItemRevision | None:
    return db.scalar(select(WorkItemRevision)
                     .where(WorkItemRevision.work_item_id == work_item_id)
                     .order_by(WorkItemRevision.revision.desc())
                     .limit(1))


def effective_item(db: Session, item: WorkItem, revision: WorkItemRevision | None = None):
    """Return source or corrected values without changing original ORM object."""
    if revision is None:
        revision = latest_revision(db, item.id)
    return SimpleNamespace(
        id=item.id,
        import_id=item.import_id,
        source_row=item.source_row,
        raw_description=revision.description if revision else item.raw_description,
        raw_quantity=str(revision.quantity) if revision else item.raw_quantity,
        normalized_unit=revision.unit if revision else item.normalized_unit,
        quantity=revision.quantity if revision else item.quantity,
        review_required=False if revision else item.review_required,
        revision_id=revision.id if revision else None,
        revision=revision.revision if revision else 0,
    )


def frozen_snapshot(run_id: str, effective) -> MatchRunItemSnapshot:
    return MatchRunItemSnapshot(
        run_id=run_id, work_item_id=effective.id, revision_id=effective.revision_id,
        description=effective.raw_description, quantity=effective.quantity,
        unit=effective.normalized_unit, review_required=effective.review_required
    )


def previously_frozen(item: WorkItem, snapshot: MatchRunItemSnapshot | None):
    """Old M2 runs predate snapshots; interpret them against original import only."""
    if snapshot is None:
        return (item.raw_description, item.quantity, item.normalized_unit, item.review_required)
    return (snapshot.description, snapshot.quantity, snapshot.unit, snapshot.review_required)


def fingerprint(effective) -> tuple:
    return (effective.raw_description, effective.quantity, effective.normalized_unit,
            effective.review_required)
