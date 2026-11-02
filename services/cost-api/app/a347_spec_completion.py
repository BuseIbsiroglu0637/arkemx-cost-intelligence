"""A3.47 — source-bound, conservative specification fact completion.

Read-only advisory data. Explicit contradictions and missing attributes stay
visible; evidence cannot approve a position or make it eligible for costing.
Never infer material or engineering attributes from lexical similarity alone.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a318_pdf_api import _read as analysis_pdf, _pdf_candidate_check
from .a326_project_evidence import (
    _block_matches, _evidence_status, _file_path, _read_file, _scan,
)
from .a343_work_scope import scope_blocker
from .database import get_db
from .matching import family
from .models import PdfCandidateSelection, User, WorkItem
from .revisions import effective_item
from .security import current_user
from .technical import extract
from .a324_ceramic_features import ceramic_features
from .a338_plaster_evidence import compare_plaster_sources

router = APIRouter(
    prefix="/api/projects/{project_id}/a347/imports/{import_id}/items/{work_item_id}",
    tags=["A3.47 Evidence-first Technical Completion"],
)

FACT_LABELS = {
    "gazbeton_strength_n_mm2": "Gazbeton dayanımı (N/mm²)",
    "gazbeton_density_kg_m3": "Gazbeton yoğunluğu (kg/m³)",
    "glaze": "Seramik yüzey özelliği",
    "surface": "Seramik yüzey bitişi",
    "rectified": "Seramik rektifiye kenar",
    "layer_thickness_mm": "Sıva kalınlığı (mm)",
    "cement_dosage_kg": "Sıva çimento dozajı",
    "concrete_class": "Beton sınıfı",
    "paint_base": "Boya türü",
    "coat_count": "Boya kat sayısı",
}
REQUIRED_BY_FAMILY = {
    "gazbeton": ("gazbeton_strength_n_mm2", "gazbeton_density_kg_m3"),
    "seramik": ("glaze", "surface", "rectified"),
    "siva": ("layer_thickness_mm",),
    "beton": ("concrete_class",),
    "boya": ("paint_base",),
}


def _clean(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value).strip().casefold()


def _explicit_excel_facts(description: str, kind: str | None) -> dict:
    if kind == "gazbeton":
        data = extract(description)
        return {key: data.get(key) for key in REQUIRED_BY_FAMILY["gazbeton"]}
    if kind == "seramik":
        data = ceramic_features(description)
        return {key: data.get(key) for key in REQUIRED_BY_FAMILY["seramik"]}
    return {}


def _summarize_facts(description: str, matches: list[dict], position=None) -> list[dict]:
    kind = family(description)
    expected = REQUIRED_BY_FAMILY.get(kind, ())
    if kind == "siva" and position is not None:
        # A3.38 restricts plaster facts to an explicit layer and compares dosage.
        comparisons = compare_plaster_sources(description, position, [
            (row["page"], row["quote"]) for row in matches
        ])
        for extra in comparisons:
            if extra["key"] == "cement_dosage_kg" and extra["key"] not in expected:
                expected = (*expected, extra["key"])
    original = _explicit_excel_facts(description, kind)
    candidate_facts = _explicit_excel_facts(position.description, kind) if position else {}
    values = defaultdict(list)
    for row in matches:
        for key, value in row["facts"].items():
            if value is not None and key in FACT_LABELS:
                values[key].append({
                    "value": value, "page": row["page"], "quote": row["quote"],
                })
    results = []
    for key in sorted(set(expected) | set(values)):
        records = values.get(key, [])
        distinct = {_clean(record["value"]) for record in records}
        explicit = original.get(key)
        if len(distinct) > 1:
            state, fact_value = "conflict", None
        elif not distinct:
            state, fact_value = "missing", None
        else:
            fact_value = records[0]["value"]
            compared = [value for value in (explicit, candidate_facts.get(key)) if value is not None]
            state = (
                "conflict" if any(_clean(value) != _clean(fact_value) for value in compared)
                else "found_for_review"
            )
        results.append({
            "key": key, "label": FACT_LABELS.get(key, key),
            "value": fact_value, "excel_value": explicit,
            "position_value": candidate_facts.get(key), "state": state,
            "evidence": records[:4],
            "additional_evidence_count": max(0, len(records)-4),
        })
    return results


def _safe_result(*, item, document_sha, document_status, candidate,
                 position_status, flags, facts, scope_conflict):
    conflicts = [fact["label"] for fact in facts if fact["state"] == "conflict"]
    missing = [fact["label"] for fact in facts if fact["state"] == "missing"]
    if scope_conflict:
        conflicts.append("İş kapsamı (söküm / temin / işçilik / montaj)")
    if position_status == "blocked":
        conflicts.append("Pozun teknik özellikleri")
    if document_status != "found_for_review" and not facts and document_status in (
        "no_document", "unreadable_text",
    ):
        missing.append("Proje teknik şartnamesi")
    # Finding facts is not permission to discard candidate-review flags.
    status = (
        "technical_conflict" if conflicts else
        "information_missing" if missing or flags or position_status == "review" else
        "evidence_for_engineer_review"
    )
    return {
        "schema": "arkemx.a347.spec_completion.v1",
        "read_only": True, "approval_allowed": False, "engineering_approved": False,
        "cost_allowed": False,
        "work_item_id": item.id, "source_row": item.source_row,
        "revision_id": item.revision_id, "document_sha256": document_sha,
        "document_status": document_status, "selected_position_code": candidate,
        "position_status": position_status, "technical_flags": flags,
        "facts": facts, "conflicts": sorted(set(conflicts)), "missing": sorted(set(missing)),
        "status": status,
        "note": "Belgeden bulunan bilgiler öneridir; mühendis incelemesi ve kaydı olmadan maliyete geçmez.",
    }


@router.get("/completion")
def specification_completion(
    project_id: UUID, import_id: UUID, work_item_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(work_item_id), WorkItem.import_id == batch.id,
    ))
    if item is None:
        raise HTTPException(404, "Metraj row not found", headers=NO_STORE)
    current = effective_item(db, item)
    selection = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.work_item_id == item.id,
    ))
    position = None
    pos_code = None
    position_status = "unselected"
    flags = []
    scope_conflict = None
    if selection:
        found_pdf = analysis_pdf(user)
        if found_pdf and selection.pdf_sha256 == found_pdf[0] and selection.revision_id == current.revision_id:
            position = next((p for p in found_pdf[1] if p.id == selection.position_code), None)
            if position:
                pos_code = position.id
                check = _pdf_candidate_check(current, position)
                position_status = check["status"]
                flags = list(check["review_flags"]) + list(check["blockers"])
                scope_conflict = scope_blocker(current.raw_description, position.description)
        if not position:
            position_status = "stale_selection"
    doc = _read_file(_file_path(user, project_id))
    document_sha = None
    matched = []
    document_status = "no_document"
    if doc:
        raw, document_sha = doc
        try:
            blocks, _ = _scan(raw)
            matched = _block_matches(current.raw_description, blocks)
            document_status = "unreadable_text" if not blocks else _evidence_status(matched)
        except ValueError:
            document_status = "unreadable_text"
    facts = _summarize_facts(current.raw_description, matched, position)
    result = _safe_result(
        item=current, document_sha=document_sha, document_status=document_status,
        candidate=pos_code, position_status=position_status,
        flags=flags, facts=facts, scope_conflict=scope_conflict,
    )
    response.headers.update(NO_STORE)
    return result
