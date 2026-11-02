"""A3.46: explain gaps in source-bound PDF poz retrieval, never create an approval.

A 'no match' means *this loaded source and these retrieval rules* did not
produce a selectable candidate. It does NOT establish that no official poz
exists in another volume, discipline, or institution.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a318_pdf_api import (
    MAX_FULL_REVIEW_ROWS, _path, _pdf_candidate_check, _read, _suggestions_result,
)
from .database import get_db
from .matching import family, similarity, tokens
from .models import User, WorkItem
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a346/imports/{import_id}",
    tags=["A3.46 Matching Audit (read-only)"],
)

RAW_CODE = re.compile(r"(?<![0-9.])15\.\d{3}\.\d{4}(?![0-9])")
MAX_NEAR_HITS = 2
AUDIT_KINDS = (
    "metraj_input_gap",
    "technical_conflict",
    "manual_code_in_pdf_not_parsed",
    "manual_code_outside_loaded_pdf",
    "possible_retrieval_gap",
    "source_scope_or_description_unknown",
)


@lru_cache(maxsize=2)
def _raw_position_codes(source_sha256: str, data: bytes) -> dict[str, int] | None:
    """PDF text mentions, not proof that a code heads a complete analysis."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            return {
                code: page_number
                for page_number, page in enumerate(pdf, start=1)
                for code in RAW_CODE.findall(page.get_text("text"))
            }
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError, RuntimeError):
        return None


def _inverted_index(positions):
    by_token = defaultdict(set)
    for position in positions:
        for word in tokens(position.description):
            if len(word) > 3:
                by_token[word].add(position.id)
    return by_token


def _retrieval_leads(description, unit, positions_by_code, index, current, *, excluded):
    """Bounded lexical diagnostic only; never a candidate or an approval.

    Require a positively shared material family, a meaningful lexical overlap
    and no technical block, otherwise the audit could suggest an unrelated poz.
    """
    item_family = family(description)
    if not item_family:
        return []
    overlap = Counter(code for word in tokens(description) if len(word) > 3
                      for code in index.get(word, ()))
    ranked = sorted(overlap, key=lambda code: (-overlap[code], code))[:30]
    found = []
    for code in ranked:
        position = positions_by_code[code]
        if family(position.description) != item_family or code in excluded:
            continue
        if unit and position.unit != unit:
            continue
        score = similarity(description, position.description)
        if score < 0.30:
            continue
        check = _pdf_candidate_check(current, position)
        if check["status"] == "blocked":
            continue
        found.append({
            "code": code, "description": position.description,
            "pdf_page": position.pdf_page, "lexical_similarity": score,
            "technical_status": check["status"],
            "selectable": False, "cost_allowed": False,
        })
    found.sort(key=lambda item: (-item["lexical_similarity"], item["code"]))
    return found[:MAX_NEAR_HITS]


def classify_missing(row, raw_codes, parsed_codes, leads):
    """Classify *why this search did not produce a candidate*, conservatively."""
    manual = row.get("manual_position")
    code = manual["position_code"] if manual and manual.get("current") else None
    if row.get("quantity") is None or not row.get("unit"):
        return "metraj_input_gap", "Metraj miktarı veya ölçü birimi eksik"
    if row.get("rejected_candidate_count", 0) > 0:
        return "technical_conflict", "Arama seçenekleri teknik kapsam nedeniyle elendi"
    if code and code not in parsed_codes and raw_codes is not None and code in raw_codes:
        return "manual_code_in_pdf_not_parsed", (
            "Girilen numara PDF metninde geçiyor; tam analiz olarak ayrıştırılamamış"
        )
    if code and code not in parsed_codes and raw_codes is not None and code not in raw_codes:
        return "manual_code_outside_loaded_pdf", (
            "Girilen numara bu PDF metninde bulunamadı; başka katalog veya özel poz olabilir"
        )
    if leads:
        return "possible_retrieval_gap", (
            "PDF'de metinsel benzerlik taşıyan poz var; otomatik eşleştirme dışarıda bırakmış"
        )
    return "source_scope_or_description_unknown", (
        "Bu PDF ve eşleştirme kurallarıyla poz doğrulanamadı; başka cilt, branş veya özel iş olabilir"
    )


def _candidate_risk(row):
    options = row["suggestions"]
    top = options[0]
    if not top.get("source_price_verified"):
        return "source_price_not_reconciled", "Kaynak analiz tutarı güvenilir biçimde ayrıştırılamadı"
    if top["technical_status"] != "compatible" or top.get("review_flags"):
        return "technical_review", "Teknik özellikler veya eksik tanım doğrulanmalı"
    if row["triage"]["group"] == "needs_info":
        return "missing_information", row["triage"]["reason"]
    if len(options) > 1 or top.get("possible_shared_scope"):
        return "ambiguous_options", "Birden fazla seçenek veya ortak iş kapsamı kontrol edilmeli"
    return "candidate_not_engineer_approved", "Poz seçeneği bulundu; mühendis onayı hâlâ gerekli"


def _summarize(source, catalog, pdf_text_index, result, effective):
    digest, positions = source
    parsed = {position.id: position for position in positions}
    index = _inverted_index(positions)
    by_item = {str(item.id): item for item in effective}
    missing_counts = Counter()
    risk_counts = Counter()
    missing_rows = []
    candidate_rows = []
    for row in result["rows"]:
        code_set = {option["code"] for option in row["suggestions"]}
        code_set.update(option["code"] for option in row.get("excluded_positions", ()))
        if row["suggestions"]:
            risk, detail = _candidate_risk(row)
            risk_counts[risk] += 1
            candidate_rows.append({
                "work_item_id": row["work_item_id"], "source_row": row["source_row"],
                "description": row["description"], "risk": risk,
                "reason": detail,
                "source_options": [
                    {"code": option["code"], "description": option["description"],
                     "pdf_page": option["source_page"],
                     "technical_status": option["technical_status"],
                     "source_price_verified": option["source_price_verified"],
                     "review_flags": option["review_flags"],
                     "selectable_for_review": True, "cost_allowed": False}
                    for option in row["suggestions"][:3]
                ],
                "excluded_count": row["rejected_candidate_count"],
                "engineer_approved": False, "cost_allowed": False,
            })
            continue
        current = by_item.get(str(row["work_item_id"]))
        leads = (_retrieval_leads(
            row["description"], row["unit"], parsed, index, current,
            excluded=code_set,
        ) if current and row.get("rejected_candidate_count", 0) == 0
           and row.get("quantity") is not None and row.get("unit") else [])
        reason_code, reason = classify_missing(row, pdf_text_index, parsed, leads)
        missing_counts[reason_code] += 1
        missing_rows.append({
            "work_item_id": row["work_item_id"], "source_row": row["source_row"],
            "description": row["description"], "quantity": row["quantity"],
            "unit": row["unit"], "reason_code": reason_code, "reason": reason,
            "technical_exclusions": row["rejected_candidate_count"],
            "excluded_examples": row.get("excluded_positions", [])[:3],
            "diagnostic_leads": leads,
            "manual_code": row["manual_position"]["position_code"] if row.get("manual_position") else None,
            "engineer_approved": False, "cost_allowed": False,
        })
    unparsed_text_codes = (
        sorted(set(pdf_text_index) - set(parsed)) if pdf_text_index is not None else None
    )
    return {
        "schema": "arkemx.a346.matching_audit.v1",
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "source_pdf_sha256": digest,
        "import_id": result["import_source"]["import_id"],
        "import_sha256": result["import_source"]["sha256"],
        "total_rows": len(result["rows"]),
        "missing_count": len(missing_rows), "candidate_count": len(candidate_rows),
        "missing_reason_counts": {kind: missing_counts[kind] for kind in AUDIT_KINDS},
        "candidate_risk_counts": dict(risk_counts),
        "source_pdf": {
            "volume": 1, "year": 2026,
            "parsed_position_count": len(positions),
            "verified_price_count": sum(pos.price_verified for pos in positions),
            "raw_code_scan_available": pdf_text_index is not None,
            "raw_text_position_codes": len(pdf_text_index) if pdf_text_index is not None else None,
            "codes_in_text_not_extracted_count": (
                len(unparsed_text_codes) if unparsed_text_codes is not None else None
            ),
            "codes_in_text_not_extracted_sample": (
                unparsed_text_codes[:12] if unparsed_text_codes is not None else []
            ),
            "note": (
                "15.x kodlarının PDF metninde geçmesi bunların tam analiz başlığı olduğu "
                "anlamına gelmez. Birden fazla cilt, kurum veya branş henüz taranmadı."
            ),
        },
        "missing_rows": missing_rows, "candidate_rows": candidate_rows,
        "note": (
            "Bu denetim yalnız mevcut 2026 Cilt 1 PDF ve seçilen Excel aktarımı içindir. "
            "Poz seçeneği veya metinsel yakınlık mühendis onayı ve maliyet izni vermez."
        ),
    }


@router.get("/audit")
def matching_audit(
    project_id: UUID, import_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    rows_count = db.scalar(select(func.count()).select_from(WorkItem).where(
        WorkItem.import_id == batch.id,
    )) or 0
    if rows_count > MAX_FULL_REVIEW_ROWS:
        raise HTTPException(422, "Import exceeds audit limit; use paged review", headers=NO_STORE)
    found = _read(user)
    if found is None:
        raise HTTPException(409, "Connect the PDF source first", headers=NO_STORE)
    digest, positions = found
    source_path = _path(user)
    # The validated source reader already checked symlink parents and hash.
    raw_codes = _raw_position_codes(digest, source_path.read_bytes())
    result = _suggestions_result(
        project_id, import_id, response, user, db, 0, MAX_FULL_REVIEW_ROWS
    )
    if result["catalog"]["sha256"] != digest or result["import_source"]["sha256"] != batch.sha256:
        raise HTTPException(409, "Source changed during audit", headers=NO_STORE)
    # Exact same effective work items used in the matching pipeline.
    from .revisions import effective_item
    items = db.scalars(select(WorkItem).where(
        WorkItem.import_id == batch.id,
    ).order_by(WorkItem.source_row, WorkItem.id)).all()
    effective = [effective_item(db, item) for item in items]
    output = _summarize(found, batch, raw_codes, result, effective)
    if len(output["missing_rows"]) + len(output["candidate_rows"]) != rows_count:
        raise HTTPException(409, "Incomplete matching audit", headers=NO_STORE)
    response.headers.update(NO_STORE)
    return output
