"""A3.47: evidence-bound field suggestions, not automatic approval or mutation.

A technical specification may *supply a missing fact for review* only when the
source block is relevant to the selected metraj line and no conflicting values
are present. Field-level comparisons are against the exact current PDF
position. They cannot sign an analysis, alter the Excel or create M5 prices.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a318_pdf_api import _pdf_candidate_check, _read as analysis_pdf
from .a326_project_evidence import (
    _block_matches, _file_path, _read_file, _scan,
)
from .a343_work_scope import scope_blocker
from .a327_additional_evidence import conflicts_with_metraj
from .database import get_db
from .excel import normalized
from .matching import family
from .models import User, WorkItem
from .revisions import effective_item
from .security import current_user
from .technical import extract
from .a324_ceramic_features import ceramic_features

router = APIRouter(
    prefix="/api/projects/{project_id}/a347/imports/{import_id}",
    tags=["A3.47 Evidence-based Technical Completion"],
)

FIELD_LABELS = {
    "gazbeton_strength_n_mm2": "Gazbeton dayanımı (N/mm²)",
    "gazbeton_density_kg_m3": "Gazbeton yoğunluğu (kg/m³)",
    "thickness_mm": "Sıva kalınlığı (mm)",
    "binder_type": "Sıva bağlayıcı türü",
    "layer_type": "Sıva katmanı",
    "layer_thickness_mm": "Katman kalınlığı (mm)",
    "cement_dosage_kg": "Çimento dozajı (kg)",
    "glaze": "Seramik sır türü",
    "surface": "Seramik yüzeyi",
    "rectified": "Seramik kenar türü",
    "paint_base": "Boya türü",
    "coat_count": "Boya kat sayısı",
    "concrete_class": "Beton sınıfı",
}
NEEDED = {
    "gazbeton": ("gazbeton_strength_n_mm2", "gazbeton_density_kg_m3"),
    "seramik": ("glaze", "surface", "rectified"),
    "siva": ("thickness_mm", "binder_type"),
    "beton": ("concrete_class",),
    "boya": ("paint_base", "coat_count"),
}


def _binder(text: str) -> str | None:
    t = normalized(text)
    if "cimento esasli" in t or "cimento harci" in t:
        return "cimento"
    if "alci esasli" in t or "alci siva" in t:
        return "alci"
    return None


def _siva_without_layer(description: str, blocks: list[tuple[int, str]]):
    """Conservative pilot fallback for 2 cm *cement based* vs gypsum plaster.

    Do not transfer values from an explicitly different binder or compound
    multi-layer specification. Inconsistent thicknesses are kept as conflicts.
    """
    if family(description) != "siva":
        return []
    from .a335_plaster_matching import plaster_stages
    if plaster_stages(description):
        return []
    left = extract(description)
    desired = _binder(description)
    matches = []
    for page, text in blocks:
        plain = normalized(text)
        if "siva" not in plain:
            continue
        # A project spec can contain several independent plaster layers.
        if plaster_stages(text):
            continue
        binder = _binder(text)
        if desired and binder and desired != binder:
            continue
        right = extract(text)
        thick = right["thickness_mm"]
        if binder is None and thick is None:
            continue
        facts = {"thickness_mm": thick, "binder_type": binder}
        matches.append({"page": page, "quote": text[:320], "facts": facts})
    return matches


def _matches(description: str, blocks: list[tuple[int, str]]):
    matches = _block_matches(description, blocks)
    if matches:
        return matches
    return _siva_without_layer(description, blocks)


def _metraj_facts(description: str, kind: str | None):
    if kind == "gazbeton":
        data = extract(description)
        return {name: data.get(name) for name in NEEDED[kind]}
    if kind == "seramik":
        data = ceramic_features(description)
        return {name: data.get(name) for name in NEEDED[kind]}
    if kind == "siva":
        data = extract(description)
        return {"thickness_mm": data.get("thickness_mm"), "binder_type": _binder(description)}
    if kind == "beton":
        from .a327_additional_evidence import CONCRETE
        m = CONCRETE.search(normalized(description))
        return {"concrete_class": f"C{m[1]}/{m[2]}" if m else None}
    if kind == "boya":
        from .a327_additional_evidence import _paint_bases, COATS
        t = normalized(description)
        bases = _paint_bases(t)
        coat = {int(a or b) for a, b in COATS.findall(t)}
        return {"paint_base": next(iter(bases)) if len(bases)==1 else None,
                "coat_count": next(iter(coat)) if len(coat)==1 else None}
    return {}


def _candidate_facts(description: str, kind: str | None):
    # Only explicit candidate words count. Blank values remain unverified.
    return _metraj_facts(description, kind)


def _compare_fields(kind, description, matches, position):
    excel = _metraj_facts(description, kind)
    candidate = _candidate_facts(position.description, kind) if position else {}
    observed: dict[str, list[dict]] = defaultdict(list)
    for match in matches:
        for key, value in match["facts"].items():
            if value is not None and key in FIELD_LABELS:
                observed[key].append({
                    "value": value, "page": match["page"], "quote": match["quote"][:320],
                })
    fields = []
    has_conflict = False
    missing = []
    for key in NEEDED.get(kind, ()):
        records = observed.get(key, [])
        distinct = {str(record["value"]) for record in records}
        from_excel = excel.get(key)
        from_position = candidate.get(key)
        conflict = len(distinct)>1 or (len(distinct)==1 and (
            (from_excel is not None and str(from_excel) not in distinct) or
            (from_position is not None and str(from_position) not in distinct)
        ))
        has_conflict = has_conflict or conflict
        source = records[0] if len(distinct)==1 else None
        status = (
            "conflict" if conflict else
            "missing" if not records else
            "supported" if from_position is not None and str(from_position) in distinct else
            "candidate_unverified"
        )
        if status in ("missing", "candidate_unverified"):
            missing.append(key)
        fields.append({
            "key": key, "label": FIELD_LABELS[key],
            "excel_value": from_excel, "pdf_value": source["value"] if source else None,
            "candidate_value": from_position,
            "status": status,
            "suggested_from_spec": (
                source["value"] if source and from_excel is None and not conflict else None
            ),
            "page": source["page"] if source else None,
            "quote": source["quote"] if source else None,
            "conflicting_values": (
                sorted(distinct) if conflict else []
            ),
        })
    return fields, has_conflict, missing


@router.get("/items/{work_item_id}/completion")
def technical_completion(
    project_id: UUID, import_id: UUID, work_item_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    position_code: Annotated[str | None, Query(max_length=80)] = None,
):
    batch = _source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(work_item_id), WorkItem.import_id == batch.id
    ))
    if not item:
        raise HTTPException(404, "Metraj not found", headers=NO_STORE)
    current = effective_item(db, item)
    kind = family(current.raw_description)
    path = _file_path(user, project_id)
    doc = _read_file(path)
    digest = doc[1] if doc else None
    blocks = []
    document_state = "missing"
    if doc:
        try:
            blocks, _ = _scan(doc[0])
            document_state = "available" if blocks else "unreadable_text"
        except ValueError:
            document_state = "unreadable_text"
    source_pdf = analysis_pdf(user)
    pdf_sha = source_pdf[0] if source_pdf else None
    position = None
    if position_code and source_pdf:
        position = next((p for p in source_pdf[1] if p.id == position_code), None)
    matches = _matches(current.raw_description, blocks) if blocks else []
    fields, field_conflict, missing = _compare_fields(
        kind, current.raw_description, matches, position
    )
    scope_problem = scope_blocker(current.raw_description, position.description) if position else None
    check = _pdf_candidate_check(current, position) if position else None
    technical_blockers = check.get("blockers", []) if check else []
    if scope_problem and scope_problem not in technical_blockers:
        technical_blockers = [*technical_blockers, scope_problem]
    if kind == "siva" and matches:
        from .a327_additional_evidence import conflicts_with_metraj
        if conflicts_with_metraj(current.raw_description, matches):
            field_conflict = True
    if field_conflict or technical_blockers:
        status = "conflicting"
        message = "Şartname, metraj veya seçilen poz arasında teknik çelişki var."
    elif not doc:
        status = "no_document"
        message = "Proje şartnamesi bağlı değil."
    elif document_state != "available":
        status = "unreadable"
        message = "Şartname PDF metni okunamadı."
    elif not matches:
        status = "not_found"
        message = "Bu imalatın teknik bilgisi şartnamede doğrulanamadı."
    elif not position:
        status = "facts_found"
        message = "Şartnameden bilgiler bulundu; doğrulanmış poz seçimi yok."
    elif missing:
        status = "partially_supported"
        message = "Bazı bilgiler bulundu; eksik özellikler veya poz tarifi mühendis incelemesi gerektiriyor."
    else:
        status = "documented_for_review"
        message = "Kontrol edilen alanlar şartnameyle uyumlu görünüyor; mühendis onayı hâlâ gerekli."
    response.headers.update(NO_STORE)
    return {
        "schema": "arkemx.a347.completion.v1",
        "read_only": True, "engineering_approved": False, "cost_allowed": False,
        "project_id": batch.project_id, "import_id": batch.id,
        "import_sha256": batch.sha256,
        "work_item_id": item.id, "source_row": item.source_row,
        "revision_id": current.revision_id,
        "spec_sha256": digest, "pdf_sha256": pdf_sha,
        "candidate_code": position_code,
        "candidate_found_in_pdf": position is not None,
        "document_state": document_state,
        "status": status, "message": message,
        "fields": fields,
        "missing_fields": missing,
        "technical_blockers": technical_blockers,
        "scope_conflict": scope_problem,
        "possible_special_analysis": not position,
        "next_step": (
            "Mevcut kaynakta uygun poz yoksa başka resmî katalogları araştır "
            "veya kaynağı/fiyatı belgeli özel analiz hazırla; otomatik fiyat verme."
            if not position else "Teknik doğrulamayı tamamla, analizi ve mühendis onayını ayrı kaydet."
        ),
    }
