"""A3.38: read-only, source-cited plaster facts (Excel, position PDF, project PDF).

A PDF mention is not automatically a technical signoff, approval or rate.
Do not assign mixed-stage dosage to either row without an explicit stage.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a318_pdf_api import _pdf_candidate_check, _read as read_positions, _saved_choice_blocked
from .a326_project_evidence import _file_path, _read_file, _scan
from .a327_additional_evidence import _layer_values
from .a335_plaster_matching import plaster_dosages, plaster_stages
from .database import get_db
from .matching import dimensions
from .models import PdfCandidateSelection, User, WorkItem
from .revisions import effective_item
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a338/imports/{import_id}/items/{work_item_id}",
    tags=["A3.38 Plaster Source Comparison (read-only)"],
)


def _one(values):
    unique = set(values)
    return next(iter(unique)) if len(unique) == 1 else None


def _spec_facts(description: str, blocks: list[tuple[int, str]]) -> tuple[list[dict], list[dict]]:
    stages = plaster_stages(description)
    if len(stages) != 1:
        return [], []
    stage = next(iter(stages))
    thickness = []
    dosage = []
    for page, quote in blocks:
        if "siva" not in quote.lower().replace("ı", "i"):
            continue
        for actual_stage, millimeters in _layer_values(quote):
            if actual_stage == stage:
                thickness.append({"value": millimeters, "page": page, "quote": quote[:320]})
        # One paragraph with both layers and one dose cannot reliably
        # attribute the dose to this layer. Preserve uncertainty.
        if plaster_stages(quote) != stages:
            continue
        values = plaster_dosages(quote)
        for value in sorted(values):
            dosage.append({"value": str(value), "page": page, "quote": quote[:320]})
    return thickness, dosage


def _fact(name, excel, position, spec_rows, expected):
    values = {str(record["value"]) for record in spec_rows}
    value = _one(values)
    if len(values) > 1:
        status = "conflict"
    elif value is None:
        status = "missing_project"
    elif expected is not None and str(expected) != value:
        status = "conflict"
    else:
        status = "evidence_found"
    return {
        "key": name, "excel": excel, "position": position,
        "project": value, "status": status,
        "evidence": [
            {"page": record["page"], "quote": record["quote"], "value": record["value"]}
            for record in spec_rows[:4]
        ], "other_evidence_count": max(0, len(spec_rows) - 4),
    }


def compare_plaster_sources(description, position, blocks):
    stages = plaster_stages(description)
    if len(stages) != 1:
        return []
    stage = next(iter(stages))
    source_thickness = dimensions(description)[1]
    pdf_thickness = dimensions(position.description)[1]
    thickness_records, dosage_records = _spec_facts(description, blocks)
    title_doses = plaster_dosages(position.description)
    scope_doses = plaster_dosages(position.scope or "")
    position_doses = title_doses | scope_doses
    metraj_doses = plaster_dosages(description)
    expected_dose = _one(position_doses) if position_doses else None
    required_dose = _one(metraj_doses) if metraj_doses else expected_dose

    return [
        {
            "key": "layer", "excel": stage, "position": (
                "/".join(sorted(plaster_stages(position.description) |
                                plaster_stages(position.scope or ""))) or None
            ), "project": None, "status": "source_only",
            "evidence": [], "other_evidence_count": 0,
        },
        _fact(
            "thickness_mm", source_thickness, pdf_thickness, thickness_records,
            source_thickness if source_thickness is not None else pdf_thickness,
        ),
        _fact(
            "cement_dosage_kg", str(_one(metraj_doses)) if len(metraj_doses) == 1 else None,
            str(expected_dose) if expected_dose is not None else None,
            dosage_records, required_dose,
        ),
        {
            "key": "coverage", "excel": "Kaba/ince satırları ayrı ölçülmüş",
            "position": "Tek pozun iki katmanı kapsayıp kapsamadığı kontrol edilir",
            "project": None, "status": "scope_review",
            "evidence": [], "other_evidence_count": 0,
        },
    ]


@router.get("/comparison")
def plaster_source_comparison(
    project_id: UUID, import_id: UUID, work_item_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    position_code: Annotated[str, Query(pattern=r"^15\.\d{3}\.\d{4}$")],
):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(work_item_id), WorkItem.import_id == batch.id,
    ))
    if item is None:
        raise HTTPException(404, "Metraj satırı bulunamadı", headers=NO_STORE)
    current = effective_item(db, item)
    if len(plaster_stages(current.raw_description)) != 1:
        raise HTTPException(422, "Yalnız tek katmanlı sıva metrajı destekleniyor", headers=NO_STORE)

    catalog = read_positions(user)
    if not catalog:
        raise HTTPException(409, "Poz PDF kaynağı bulunamadı", headers=NO_STORE)
    digest, positions = catalog
    selected = next((p for p in positions if p.id == position_code), None)
    if selected is None:
        raise HTTPException(404, "Poz bu PDF kaynağında bulunamadı", headers=NO_STORE)
    check = _pdf_candidate_check(current, selected)
    saved = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.work_item_id == item.id,
    ))
    stale_code = None
    if saved and (
        saved.pdf_sha256 != digest or saved.revision_id != current.revision_id
        or _saved_choice_blocked(current, saved, {p.id: p for p in positions})
    ):
        stale_code = saved.position_code
    doc = _read_file(_file_path(user, project_id))
    blocks: list[tuple[int, str]] = []
    doc_sha = None
    document_state = "missing"
    if doc:
        raw, doc_sha = doc
        try:
            blocks, _ = _scan(raw)
            document_state = "available" if blocks else "unreadable"
        except ValueError:
            document_state = "unreadable"

    response.headers.update(NO_STORE)
    return {
        "position_code": selected.id,
        "metraj_revision_id": current.revision_id,
        "analysis_pdf_sha256": digest,
        "position_pdf_page": selected.pdf_page,
        "document_sha256": doc_sha,
        "document_state": document_state,
        "source_checks": compare_plaster_sources(current.raw_description, selected, blocks),
        "candidate_blocked": check["status"] == "blocked",
        "old_selection_stale_code": stale_code,
        "engineering_approved": False, "cost_allowed": False,
    }
