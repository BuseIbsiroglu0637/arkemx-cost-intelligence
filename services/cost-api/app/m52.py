"""M5.2: cautious read-only Excel revision preview and explicit append-only apply.

Comparison NEVER inherits old technical approvals or asserts that a moved/changed
row is the same engineering work item. Cost impacts are historical-price *what-if*
only. All old uploads and M5 estimates remain immutable.
"""
import hashlib
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .security import current_user
from .models import (
    User, ImportBatch, WorkItem, CostEstimate, CostEstimateLine, MetrajRevisionEvent
)
from .m2 import tenant_project
from .m5 import get_estimate, _money, _sha
from .m43 import guard_no_active
from .revisions import effective_item
from .excel import read_metraj, normalized, ExcelValidationError, safe_name
from .main import load_upload

router = APIRouter(prefix="/api/projects/{project_id}/m52", tags=["M5.2 Revised Excel"])
ROW_LIMIT = 500
ZERO = Decimal("0.00")


def _current_import(db, project_id):
    return db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()))


def _validated(content, sheet, header_row, description_column, quantity_column, unit_column):
    try:
        result = read_metraj(content, sheet=sheet, header_row=header_row,
            columns={"description": description_column, "quantity": quantity_column, "unit": unit_column})
    except ExcelValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result["row_count"] > ROW_LIMIT:
        raise HTTPException(422, "M5.2 pilot limit: at most 500 revised rows")
    return result


def _entry(row):
    """Do not pretend descriptions define stable identities."""
    return {"source_row": row.source_row,
            "description": row.raw_description,
            "quantity": str(row.quantity) if row.quantity is not None else None,
            "unit": row.normalized_unit,
            "review_required": row.review_required}


def _comparison(old_rows, new_rows, priced):
    old = {r["source_row"]: r for r in old_rows}
    new = {r["source_row"]: r for r in new_rows}
    if len(old) != len(old_rows) or len(new) != len(new_rows):
        raise HTTPException(409, "Duplicate Excel source rows detected")
    # Repeated descriptions are not reliable row identities when worksheets are rearranged.
    old_counts = Counter((normalized(r["description"]), r["unit"]) for r in old_rows)
    new_counts = Counter((normalized(r["description"]), r["unit"]) for r in new_rows)
    old_by_row = {r["source_row"]: r for r in old_rows}
    result = []
    summary = Counter()
    estimated_delta = ZERO
    fully_priced = True
    for number in sorted(set(old) | set(new)):
        a, b = old.get(number), new.get(number)
        delta = None
        is_safe = False
        if a is None:
            status = "added"
        elif b is None:
            status = "removed"
        elif a["review_required"] or b["review_required"] or a["quantity"] is None or b["quantity"] is None:
            status = "needs_data_review"
        elif normalized(a["description"]) != normalized(b["description"]) or a["unit"] != b["unit"]:
            status = "identity_or_scope_changed"
        elif old_counts[(normalized(a["description"]), a["unit"])] > 1 or new_counts[(normalized(b["description"]), b["unit"])] > 1:
            status = "duplicate_identity_review"
        elif Decimal(a["quantity"]) != Decimal(b["quantity"]):
            status = "quantity_changed"
            is_safe = True
        else:
            status = "unchanged"
            is_safe = True
        # Only exact, unique unchanged identity, known unit, and a verified
        # historical estimate permit a provisional quantity cost impact.
        if a and b and is_safe and a["unit"] is not None and a["quantity"] is not None:
            old_item = priced.get(number)
            if (old_item and old_item["unit"] == a["unit"] and
                    old_item["description"] == a["description"] and
                    old_item["quantity"] == Decimal(a["quantity"])):
                price = old_item["price"]
                delta = _money((Decimal(b["quantity"]) - Decimal(a["quantity"])) * price)
                estimated_delta += delta
            elif status == "quantity_changed":
                fully_priced = False
        elif status != "unchanged":
            fully_priced = False
        summary[status] += 1
        result.append({
            "source_row": number, "status": status,
            "old_description": a["description"] if a else None,
            "new_description": b["description"] if b else None,
            "old_quantity": a["quantity"] if a else None,
            "new_quantity": b["quantity"] if b else None,
            "old_unit": a["unit"] if a else None,
            "new_unit": b["unit"] if b else None,
            "issues": (b.get("issues", []) if b else []),
            "indicative_delta": str(delta) if delta is not None else None,
            "requires_engineer_review": status != "unchanged",
            "identity_confirmed": is_safe,
        })
    return {
        "counts": dict(summary),
        "changed_rows": sum(count for state, count in summary.items() if state != "unchanged"),
        "unknown_cost_effect": not fully_priced,
        "known_quantity_effect": str(estimated_delta),
        "fully_attributable_quantity_effect": str(estimated_delta) if fully_priced else None,
        "items": result,
    }


def _preview_data(db, user, project_id, content, parsed, estimate_id):
    tenant_project(db, user, project_id)
    baseline = _current_import(db, project_id)
    if not baseline:
        raise HTTPException(409, "First import baseline metraj via M1")
    if baseline.row_count > ROW_LIMIT:
        raise HTTPException(422, "M5.2 pilot limit: at most 500 baseline rows")
    old_objects = db.scalars(select(WorkItem).where(WorkItem.import_id == baseline.id)
        .order_by(WorkItem.source_row)).all()
    if len(old_objects) != baseline.row_count:
        raise HTTPException(409, "Baseline row count mismatch")
    old_rows = []
    for row in old_objects:
        effective = effective_item(db, row)
        old_rows.append({
            "source_row": row.source_row, "description": effective.raw_description,
            "quantity": str(effective.quantity) if effective.quantity is not None else None,
            "unit": effective.normalized_unit, "review_required": effective.review_required
        })
    priced = {}
    if estimate_id:
        verified = get_estimate(project_id, estimate_id, user, db)
        estimate = db.get(CostEstimate, estimate_id)
        if not estimate or estimate.import_id != baseline.id:
            raise HTTPException(409, "Selected M5 estimate must belong to current baseline metraj")
        estimate_lines = db.scalars(select(CostEstimateLine)
            .where(CostEstimateLine.estimate_id == estimate_id)).all()
        baseline_items = {r.id: r.source_row for r in old_objects}
        for line in estimate_lines:
            if baseline_items.get(line.work_item_id) != line.source_row:
                raise HTTPException(409, "Pricing source row mismatch")
            priced[line.source_row] = {
                "description": line.description, "unit": line.unit,
                "quantity": Decimal(line.quantity), "price": Decimal(line.unit_price)
            }
    else:
        verified = None
    changes = _comparison(old_rows, parsed["items"], priced)
    revision_hash = hashlib.sha256(content).hexdigest()
    return {
        "baseline_import_id": baseline.id,
        "baseline_filename": baseline.original_filename,
        "baseline_sha256": baseline.sha256,
        "revision_sha256": revision_hash,
        "revision_sheet": parsed["sheet"],
        "row_count_old": len(old_rows),
        "row_count_new": parsed["row_count"],
        "review_count_new": parsed["review_count"],
        "baseline_estimate_id": estimate_id,
        "baseline_estimate_total": verified["total"] if verified else None,
        **changes,
        "requires_fresh_m43": True,
        "approvals_transferred": False,
        "note": "Only same-row unique unchanged technical descriptions/units can use a historical manual price for indicative quantity impact. New Excel receives fresh identities; all new approvals require new M4.3/M4.2. No official rate or binding estimate is generated."
    }


async def _upload_and_parse(file, sheet, header_row, description_column, quantity_column, unit_column):
    content = await load_upload(file)
    return content, _validated(content, sheet, header_row, description_column,
                                quantity_column, unit_column)


@router.post("/preview")
async def preview_revision(project_id: str, file: UploadFile = File(...),
    sheet: str | None = Form(None), header_row: int = Form(1, ge=1, le=30),
    description_column: str | None = Form(None), quantity_column: str | None = Form(None),
    unit_column: str | None = Form(None), estimate_id: str | None = Form(None),
    user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Authorize BEFORE touching the uploaded workbook.
    tenant_project(db, user, project_id)
    content, parsed = await _upload_and_parse(file, sheet, header_row,
                                              description_column, quantity_column, unit_column)
    return _preview_data(db, user, project_id, content, parsed, estimate_id)


@router.post("/apply", status_code=201)
async def apply_revision(project_id: str, file: UploadFile = File(...),
    expected_baseline_id: str = Form(..., min_length=36, max_length=36),
    expected_revision_sha256: str = Form(..., min_length=64, max_length=64),
    reason: str = Form(..., min_length=10, max_length=500),
    sheet: str | None = Form(None), header_row: int = Form(1, ge=1, le=30),
    description_column: str | None = Form(None), quantity_column: str | None = Form(None),
    unit_column: str | None = Form(None), estimate_id: str | None = Form(None),
    user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    guard_no_active(db, project_id)
    content, parsed = await _upload_and_parse(file, sheet, header_row,
                                              description_column, quantity_column, unit_column)
    result = _preview_data(db, user, project_id, content, parsed, estimate_id)
    if result["baseline_import_id"] != expected_baseline_id:
        raise HTTPException(409, "Metraj baseline changed since preview. Recheck the current version")
    if result["revision_sha256"] != expected_revision_sha256:
        raise HTTPException(409, "Uploaded revised file differs from reviewed preview")
    if result["baseline_sha256"] == result["revision_sha256"]:
        raise HTTPException(409, "Revised file is identical to current Excel. No duplicate import")
    if result["changed_rows"] == 0:
        raise HTTPException(409, "No changed metraj rows found")
    if len(reason.strip()) < 10:
        raise HTTPException(422, "Revision reason requires at least 10 meaningful characters")
    filename = safe_name(file.filename or "revised.xlsx")
    revision_id = str(uuid4())
    key = f"{user.organization_id}/{project_id}/{revision_id}.xlsx"
    storage_root = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
    path = storage_root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        with path.open("xb") as output:
            output.write(content)
        path.chmod(0o600)
        batch = ImportBatch(id=revision_id, project_id=project_id, created_by_id=user.id,
            original_filename=filename, sha256=result["revision_sha256"],
            file_size=len(content), stored_key=key, sheet_name=parsed["sheet"],
            row_count=parsed["row_count"])
        db.add(batch)
        for row in parsed["items"]:
            db.add(WorkItem(import_id=revision_id, source_row=row["source_row"],
                raw_description=row["description"], raw_quantity=row["raw_quantity"],
                raw_unit=row["raw_unit"], quantity=row["quantity"], normalized_unit=row["unit"],
                review_required=row["review_required"],
                warnings_json=json.dumps(row["issues"], ensure_ascii=False)))
        audit = MetrajRevisionEvent(organization_id=user.organization_id, project_id=project_id,
            baseline_import_id=result["baseline_import_id"], new_import_id=revision_id,
            baseline_estimate_id=estimate_id, old_sha256=result["baseline_sha256"],
            new_sha256=result["revision_sha256"], summary_json=snapshot,
            result_sha256=_sha(result), reason=reason.strip(), created_by_id=user.id)
        db.add(audit)
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {"id": audit.id, "import_id": revision_id,
            "revision_sha256": result["revision_sha256"],
            "baseline_sha256": result["baseline_sha256"],
            "changed_rows": result["changed_rows"], "requires_fresh_m43": True,
            "approvals_transferred": False,
            "note": "New immutable import recorded. Run M4.3 on revised Excel; inspect every proposed poz in M4.2 before creating new M5 draft."}


@router.get("/history")
def revision_history(project_id: str, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    rows = db.scalars(select(MetrajRevisionEvent)
       .where(MetrajRevisionEvent.project_id == project_id,
              MetrajRevisionEvent.organization_id == user.organization_id)
       .order_by(MetrajRevisionEvent.created_at.desc(), MetrajRevisionEvent.id.desc())
       .limit(50)).all()
    for row in rows:
        try:
            content = json.loads(row.summary_json)
        except (ValueError, TypeError):
            raise HTTPException(409, "Metraj revision audit data corrupted") from None
        if _sha(content) != row.result_sha256:
            raise HTTPException(409, "Metraj revision comparison audit SHA mismatch")
    return [{"id": r.id, "baseline_import_id": r.baseline_import_id,
             "new_import_id": r.new_import_id,
             "baseline_sha256": r.old_sha256, "revision_sha256": r.new_sha256,
             "result_sha256": r.result_sha256, "reason": r.reason,
             "created_at": r.created_at,
             "counts": json.loads(r.summary_json).get("counts", {}),
             "changed_rows": json.loads(r.summary_json).get("changed_rows", 0),
             "requires_fresh_m43": True, "approvals_transferred": False}
            for r in rows]
