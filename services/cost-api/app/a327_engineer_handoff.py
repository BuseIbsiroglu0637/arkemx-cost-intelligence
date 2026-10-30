"""A3.27.1: read-only evidence handoff queue, never engineering approval.

Only explicit, current project PDF evidence and the saved analysis-PDF candidate
can support the "documented_for_review" state. All statuses still require a
qualified human engineering decision in a separate authorized workflow.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a327_additional_evidence import conflicts_with_metraj
from .a318_pdf_api import _pdf_candidate_check, _read as read_analysis_pdf
from .a326_project_evidence import (
    _block_matches, _evidence_status, _file_path, _position_consistency,
    _read_file, _scan,
)
from .a335_plaster_matching import plaster_stages
from .a338_plaster_evidence import compare_plaster_sources
from .database import get_db
from .matching import family
from .models import PdfCandidateSelection, User, WorkItem
from .revisions import effective_item
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a327",
    tags=["A3.27 Engineer Handoff (read-only)"],
)

# A checklist is NOT a claim that these attributes are absent. It lists
# what a qualified reviewer must verify from the project and official poz.
CHECKS = {
    "siva": ["Katmanların ayrı kalınlıkları", "Harç/çimento dozajı", "İmalat kapsamı ve mükerrer fiyat riski"],
    "beton": ["Beton sınıfı", "Uygulama yeri ve miktar/birim", "Poz kapsamı ve kaynak belge"],
    "boya": ["Boya türü", "Kat sayısı ve yüzey hazırlığı", "Uygulama kapsamı"],
    "seramik": ["Seramik türü ve yüzeyi", "Derz genişliği", "Karo kalınlığı ve uygulama detayları"],
    "gazbeton": ["Duvar kalınlığı", "Dayanım ve yoğunluk", "Uygulama/işçilik kapsamı"],
}
SUPPORTED = frozenset(("gazbeton", "seramik"))


def _row_status(
    current, item: WorkItem, blocks, document_state: str, saved, positions, source_sha
) -> dict:
    description = current.raw_description
    kind = family(description)
    required = CHECKS.get(kind, ["Proje malzemesi ve teknik tarifi", "Poz kapsamı ve ölçü birimi"])
    row = {
        "work_item_id": item.id,
        "source_row": item.source_row,
        "description": description,
        "revision_id": current.revision_id,
        "status": "manual_review",
        "reason": "Bu imalatta otomatik belge karşılaştırması henüz desteklenmiyor.",
        "checks": required,
        "evidence_page": None,
        "evidence_facts": {},
        "evidence_quote": None,
        "saved_candidate": None,
        "document_sha256": source_sha,
        "engineering_approved": False,
        "cost_allowed": False,
    }
    if current.quantity is None or not current.normalized_unit or current.review_required:
        row.update(status="input_review", reason="Metraj miktarı, birimi veya giriş açıklaması kontrol edilmeli.")
        return row
    if kind == "siva":
        # A3.40: proposals for a saved single-layer plaster poz were
        # unreachable because the generic partial-evidence branch never
        # populated saved_candidate. Never equate "has a PDF" with approval.
        if document_state != "available":
            row.update(status="needs_document", reason="Proje teknik şartnamesi okunamıyor.")
            return row
        matches = _block_matches(description, blocks)
        if not matches:
            row.update(status="needs_document",
                       reason="Şartnamede bu sıva katmanının teknik bilgisi bulunamadı.")
            return row
        row["evidence_page"] = matches[0]["page"]
        row["evidence_quote"] = matches[0]["quote"]
        row["evidence_facts"] = {
            key: value for match in matches for key, value in match["facts"].items()
            if value is not None
        }
        if _evidence_status(matches) == "conflicting" or conflicts_with_metraj(description, matches):
            row.update(status="conflicting",
                       reason="Şartnamedeki sıva kalınlığı veya dozaj bilgisi çelişkili.")
            return row
        if saved is None:
            row.update(status="needs_candidate", reason="Şartname var; kayıtlı sıva pozu yok.")
            return row
        if not positions or saved.pdf_sha256 != positions[0] or saved.revision_id != current.revision_id:
            row.update(status="stale_candidate",
                       reason="Pozun PDF kaynağı veya metraj revizyonu değişmiş.")
            return row
        position = next((p for p in positions[1] if p.id == saved.position_code), None)
        if position is None:
            row.update(status="stale_candidate", reason="Poz güncel analiz PDF'sinde bulunamadı.")
            return row
        if (_pdf_candidate_check(current, position)["status"] == "blocked"
                or position.unit != current.normalized_unit
                or plaster_stages(position.description) != plaster_stages(description)):
            row.update(status="conflicting", reason="Pozun katmanı veya uygulama kapsamı metrajla uyuşmuyor.")
            return row
        row["saved_candidate"] = position.id
        facts = {
            field["key"]: field
            for field in compare_plaster_sources(description, position, blocks)
        }
        # The actual project PDF must explicitly support BOTH the stated
        # metraj thickness and the selected poz's cement dosage. A generic
        # mention or shared kaba+ince paragraph is never sufficient.
        required = ("thickness_mm", "cement_dosage_kg")
        ready = all(
            facts.get(key, {}).get("status") == "evidence_found"
            and facts[key].get("project") is not None
            for key in required
        )
        if ready:
            row.update(
                status="documented_for_review",
                reason="DEMO şartname kalınlık ve dozajı seçili pozla uyumlu. "
                       "Kapsam ve teknik karar insan incelemesi gerektirir.",
            )
        else:
            row.update(
                status="document_evidence_for_review",
                reason="Poz kayıtlı; teknik bilgiler eksik veya çelişkili. "
                       "Analiz taslağı düzenlenebilir, pilot onay bekler.",
            )
        return row

    if kind not in SUPPORTED:
        if document_state != "available":
            return row
        facts = _block_matches(description, blocks)
        if not facts:
            row["reason"] = "Şartnamede bu imalat için karşılaştırılabilir açık bilgi bulunamadı."
            return row
        row["evidence_page"] = facts[0]["page"]
        row["evidence_quote"] = facts[0]["quote"]
        # Present only facts stated in the PDF, not inferred from other works.
        row["evidence_facts"] = {
            key: value for match in facts for key, value in match["facts"].items()
            if value is not None
        }
        if _evidence_status(facts) == "conflicting" or conflicts_with_metraj(description, facts):
            row.update(status="conflicting",
                       reason="Şartnamede birden fazla değer veya metrajla açık uyuşmazlık var.")
        else:
            row.update(
                status="document_evidence_for_review",
                reason="Şartnamede satıra ait bazı bilgiler bulundu. Poz, dozaj, kapsam ve kalan teknik şartlar henüz doğrulanmadı.",
            )
        return row
    if document_state != "available":
        row.update(
            status="needs_document",
            reason="Proje teknik şartnamesi bulunamadı veya PDF metni okunamadı.",
        )
        return row
    matches = _block_matches(description, blocks)
    status = _evidence_status(matches)
    if status == "conflicting":
        row.update(
            status="conflicting",
            reason="Şartnamede çelişen teknik bilgiler var; mühendis incelemesi gerekiyor.",
            evidence_page=matches[0]["page"],
        )
        return row
    if status != "found_for_review":
        row.update(status="needs_document", reason="Bu satır için şartnamede karşılaştırılabilir bilgi bulunamadı.")
        return row
    row["evidence_page"] = matches[0]["page"]
    row["evidence_quote"] = matches[0]["quote"]
    row["evidence_facts"] = {
        key: value for match in matches for key, value in match["facts"].items()
        if value is not None
    }
    if saved is None:
        row.update(status="needs_candidate", reason="Şartname kanıtı var fakat henüz kaydedilmiş poz yok.")
        return row
    if not positions or saved.pdf_sha256 != positions[0] or saved.revision_id != current.revision_id:
        row.update(status="stale_candidate", reason="Pozun kaynak PDF'si veya metraj revizyonu değişmiş.")
        return row
    position = next((p for p in positions[1] if p.id == saved.position_code), None)
    if position is None:
        row.update(status="stale_candidate", reason="Kaydedilmiş poz güncel analiz PDF'sinde bulunmuyor.")
        return row
    row["saved_candidate"] = position.id
    comparison = _position_consistency(matches, position.description)
    if comparison == "conflicts":
        row.update(status="conflicting", reason="Şartnamedeki teknik özellikler kayıtlı pozla uyuşmuyor.")
    elif comparison == "matches_examined_facts":
        row.update(
            status="documented_for_review",
            reason="İncelenen teknik özellikler aynı. Diğer şartlar ve mühendis onayı hâlâ gerekli.",
        )
    else:
        row.update(status="needs_document", reason="Pozun karşılaştırılması için yeterli açık teknik özellik bulunamadı.")
    return row


@router.get("/imports/{import_id}/readiness")
def engineering_readiness(
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
        select(WorkItem).where(WorkItem.import_id == batch.id)
        .order_by(WorkItem.source_row, WorkItem.id)
        .offset(offset).limit(limit + 1)
    ).all()
    visible = items[:limit]
    selections = (
        db.scalars(select(PdfCandidateSelection).where(
            PdfCandidateSelection.organization_id == user.organization_id,
            PdfCandidateSelection.project_id == batch.project_id,
            PdfCandidateSelection.import_id == batch.id,
            PdfCandidateSelection.work_item_id.in_([item.id for item in visible]),
        )).all() if visible else []
    )
    saved_by_item = {row.work_item_id: row for row in selections}

    doc = _read_file(_file_path(user, project_id))
    blocks = []
    source_sha = None
    document_state = "missing"
    if doc:
        raw, source_sha = doc
        try:
            blocks, _ = _scan(raw)
            document_state = "available" if blocks else "unreadable"
        except ValueError:
            document_state = "unreadable"
    # Only read the price/analysis catalog when an active selection needs it.
    catalog = read_analysis_pdf(user) if selections and document_state == "available" else None
    rows = [
        _row_status(
            effective_item(db, item), item, blocks, document_state,
            saved_by_item.get(item.id), catalog, source_sha,
        )
        for item in visible
    ]

    # Only existing pilot records are checked. The same source fingerprint
    # as the item-level pilot API prevents a stale accept from being displayed
    # as a fresh list approval. This is NOT engineering/M5 approval.
    from .a327_decisions import _evidence_fingerprint
    from .a330_review_store import ProposedAnalysisRevision
    from .a331_pilot_review_store import PilotTechnicalReviewEvent

    for item, row in zip(visible, rows):
        row["pilot_confirmed"] = False
        row["pilot_status"] = "none"
        if not saved_by_item.get(item.id):
            continue
        latest = db.scalar(select(PilotTechnicalReviewEvent).where(
            PilotTechnicalReviewEvent.organization_id == user.organization_id,
            PilotTechnicalReviewEvent.project_id == batch.project_id,
            PilotTechnicalReviewEvent.import_id == batch.id,
            PilotTechnicalReviewEvent.work_item_id == item.id,
        ).order_by(PilotTechnicalReviewEvent.sequence.desc()).limit(1))
        if latest is None:
            continue

        revision = db.scalar(select(ProposedAnalysisRevision).where(
            ProposedAnalysisRevision.organization_id == user.organization_id,
            ProposedAnalysisRevision.project_id == batch.project_id,
            ProposedAnalysisRevision.import_id == batch.id,
            ProposedAnalysisRevision.work_item_id == item.id,
        ).order_by(ProposedAnalysisRevision.version.desc()).limit(1))
        current = effective_item(db, item)
        fingerprint = _evidence_fingerprint(
            batch, item, current, saved_by_item.get(item.id), catalog,
            source_sha, row,
        )
        valid = (
            row["status"] == "documented_for_review"
            and revision is not None
            and revision.candidate_code == row["saved_candidate"]
            and revision.source_fingerprint == fingerprint
            and latest.source_fingerprint == fingerprint
            and latest.analysis_revision_id == revision.id
        )
        row["pilot_status"] = (
            ("confirmed" if latest.action == "accept" else "reopened")
            if valid else "stale"
        )
        row["pilot_confirmed"] = bool(valid and latest.action == "accept")
    response.headers.update(NO_STORE)
    return {
        "schema": "arkemx.a327.readiness.v1",
        "read_only": True,
        "approval_allowed": False,
        "engineering_approved": False,
        "cost_allowed": False,
        "project_id": str(project_id),
        "import_id": batch.id,
        "source_sha256": source_sha,
        "document_state": document_state,
        "rows": rows,
        "next_offset": offset + limit if len(items) > limit else None,
    }
