"""A3.49.2 — read-only candidate discovery from the verified permanent 2026 PDF.

A retrieved code is a POSSIBLE position, never a correct/approved engineering
match. Explicit material, dimension, scope or binder contradictions are rejected,
not concealed by a high lexical score. This module cannot write costs/decisions.
"""
from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source as import_source
from .a343_work_scope import scope_blocker
from .a347_spec_completion import work_scope
from .a348_catalog_library_api import _source as price_source
from .a348_analysis_library_api import _source as analysis_source
from .a349_metraj_understanding import describe_metraj
from .database import get_db
from .excel import normalized
from .matching import similarity
from .models import User, WorkItem
from .revisions import effective_item
from .security import current_user
from .technical import compare

router = APIRouter(
    prefix="/api/projects/{project_id}/a349",
    tags=["A3.49.2 PDF Catalog Candidate Discovery"],
)
VERSION = "a3492-verified-catalog-lexical-v1"
POSITION_CODE = re.compile(r"(?<!\w)\d{2}\.\d{3}\.\d{4}(?!\w)")
WORDS = re.compile(r"[a-z0-9]{3,}")
STOP = frozenset({
    "bir", "ve", "ile", "olan", "ilgili", "imalat", "imalati", "is", "isler",
    "yapi", "yapil", "yapilmasi", "yapilacak", "uygulan", "uygulanmasi",
    "kullan", "malzeme", "dahil", "icin", "her", "olan", "olarak", "tur",
    "isleri", "kadar", "metraj", "genel", "poz", "tespit", "icin",
})
MAX_SCAN = 180
MAX_CANDIDATES = 3
MAX_REJECTED = 3


def _tokens(text: str) -> set[str]:
    return {
        w[:5] for w in WORDS.findall(normalized(text).replace("×", "x"))
        if w not in STOP and w[:4] not in {
            "yapi", "uygu", "imal", "maly", "dahi", "isle", "gene",
        }
    }


def _ranked_prefilter(description: str, records: list[dict]) -> list[tuple[int, dict]]:
    """Bound expensive comparisons with a deterministic source-token filter.

    Never search other tenant source indices, the web, or a generated catalogue.
    Generic common words have deliberately lower value than work-specific terms.
    """
    query = _tokens(description)
    requested_codes = set(POSITION_CODE.findall(description))
    if not query and not requested_codes:
        return []
    frequency = Counter()
    # Count document frequency (not occurrences within one verbose PDF row).
    candidate_tokens: list[set[str]] = []
    for record in records:
        words = _tokens(record["description"] + " " + (record.get("parent_description") or ""))
        candidate_tokens.append(words)
        frequency.update(words)
    ranked = []
    for record, found in zip(records, candidate_tokens):
        if record["code"] in requested_codes:
            ranked.append((10**9, record))
            continue
        intersection = query & found
        if not intersection:
            continue
        # Prefer distinct rare construction tokens, avoid generic "duvar/kaplama"
        # dominating the retrieval just because they appear in every row.
        rarity = sum(min(100, len(records) // (1 + frequency[word])) for word in intersection)
        rank = 40 * len(intersection) + rarity - 2 * len(query - found)
        ranked.append((rank, record))
    ranked.sort(key=lambda row: (-row[0], row[1]["code"]))
    return ranked[:MAX_SCAN]


def _family_guard(left: dict, right: dict) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    reviews: list[str] = []
    source_families = set(left["material_families"])
    pos_families = set(right["material_families"])
    if source_families and pos_families and not (source_families & pos_families):
        blockers.append("MATERIAL_FAMILY_MISMATCH")
    elif source_families and not pos_families:
        reviews.append("PDF_MATERIAL_FAMILY_UNVERIFIED")
    elif not source_families:
        reviews.append("EXCEL_MATERIAL_FAMILY_UNVERIFIED")
    if left["binder_materials"]:
        if right["binder_materials"] and set(left["binder_materials"]).isdisjoint(right["binder_materials"]):
            blockers.append("PLASTER_BINDER_MISMATCH")
        elif not right["binder_materials"]:
            reviews.append("PLASTER_BINDER_UNVERIFIED")
    return blockers, reviews


def _scope_guard(excel_desc: str, pdf_desc: str, left_scope: str, right_scope: str) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    reviews: list[str] = []
    guard = scope_blocker(excel_desc, pdf_desc)
    if guard:
        blockers.append(guard)
    # Restrict only explicit declarations. A missing PDF scope is NOT proof
    # that a combined official poz can be used as labor-only/material-only.
    if left_scope == "labor_only" and right_scope != "labor_only":
        if right_scope in {"material_only", "material_and_labor"}:
            blockers.append("WORK_SCOPE_LABOR_ONLY_MISMATCH")
        else:
            reviews.append("PDF_LABOR_ONLY_SCOPE_UNVERIFIED")
    elif left_scope == "material_only" and right_scope != "material_only":
        if right_scope in {"demolition", "material_and_labor", "execution_unspecified"}:
            blockers.append("WORK_SCOPE_MATERIAL_ONLY_MISMATCH")
        else:
            reviews.append("PDF_MATERIAL_ONLY_SCOPE_UNVERIFIED")
    elif left_scope == "material_and_labor" and right_scope in {"labor_only", "material_only"}:
        blockers.append("WORK_SCOPE_COMBINED_MISMATCH")
    if left_scope == "demolition" and right_scope != "demolition":
        blockers.append("WORK_SCOPE_DEMOLITION_MISMATCH")
    elif right_scope == "demolition" and left_scope != "demolition":
        blockers.append("WORK_SCOPE_DEMOLITION_MISMATCH")
    return blockers, reviews


def discover_candidates(description: str, unit: str | None, quantity: Decimal | None,
                        catalog: dict, analysis: dict | None = None,
                        *, input_review_required: bool = False) -> dict:
    """Pure bounded candidate discovery; review states never grant approval."""
    interpreted = describe_metraj(
        description, unit, quantity,
        input_review_required=input_review_required,
    )
    if interpreted["status"] in {"multiple_works_for_review", "insufficient_input"}:
        return {
            "version": VERSION, "status": "needs_input_review",
            "reason": "Excel satırındaki farklı imalatları ayır veya açıklamayı tamamla.",
            "understanding": interpreted,
            "candidates": [], "blocked_examples": [], "scanned_count": 0,
            "candidate_count": 0, "approval_allowed": False, "cost_allowed": False,
        }
    records = catalog["records"]
    preselected = _ranked_prefilter(description, records)
    analysis_codes = {
        row["code"] for row in analysis["records"]
    } if analysis is not None else set()
    admitted: list[tuple[float, dict]] = []
    blocked: list[tuple[float, dict]] = []
    for lexical_rank, record in preselected:
        text = record["description"]
        right = describe_metraj(text, record["unit"], None)
        family_blockers, family_reviews = _family_guard(interpreted, right)
        scope_blockers, scope_reviews = _scope_guard(
            description, text, interpreted["work_scope"], right["work_scope"],
        )
        technical = compare(
            description, unit, text, record["unit"],
            quantity_known=quantity is not None,
            review_required=input_review_required,
        )
        blockers = sorted(set(technical["blockers"] + family_blockers + scope_blockers))
        reviews = sorted(set(
            technical["review_flags"] + family_reviews + scope_reviews
            + interpreted["review_flags"]
        ))
        if record["unit"] is None:
            reviews.append("PDF_UNIT_UNVERIFIED")
        if record["unit_price"] is None:
            reviews.append("PDF_PRICE_UNAVAILABLE")
        # PDF descriptions can omit explicit material/dimensional details;
        # even an apparent perfect match is only a possible candidate.
        score = similarity(description, text)
        rank = float(lexical_rank) + score * 100
        entry = {
            "code": record["code"], "description": text,
            "kind": record["kind"], "unit": record["unit"],
            "unit_price": record["unit_price"], "price_status": record["price_status"],
            "pdf_page": record["pdf_page"], "pdf_source_sha256": catalog["source_sha256"],
            "analysis_cilt1_linked": record["code"] in analysis_codes,
            "lexical_similarity": score,
            "score_is_probability": False, "technical_compliance_verified": False,
            "technical_review_required": True,
            "technical_status": "blocked" if blockers else "review",
            "blockers": blockers, "review_flags": sorted(set(reviews)),
            "matched_attributes": technical["matches"],
            "approval_allowed": False, "cost_allowed": False,
        }
        if blockers:
            blocked.append((rank, entry))
        else:
            admitted.append((rank, entry))
    admitted.sort(key=lambda x: (-x[0], x[1]["code"]))
    blocked.sort(key=lambda x: (-x[0], x[1]["code"]))
    return {
        "version": VERSION,
        "status": "candidates_for_engineer_review" if admitted else "no_safe_candidates_found",
        "reason": None if admitted else
            "Bu kaynak taramasında teknik çelişkisiz poz adayı bulunamadı; başka kaynak veya teknik şartname kontrolü gerekir.",
        "understanding": interpreted,
        "candidates": [record for _, record in admitted[:MAX_CANDIDATES]],
        "blocked_examples": [record for _, record in blocked[:MAX_REJECTED]],
        "scanned_count": len(preselected),
        "candidate_count": len(admitted),
        "approval_allowed": False, "cost_allowed": False,
    }


@router.get("/imports/{import_id}/items/{work_item_id}/candidates")
def preview_pdf_candidates(
    project_id: UUID, import_id: UUID, work_item_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = import_source(db, user, str(project_id), str(import_id))
    item = db.scalar(
        select(WorkItem).where(
            WorkItem.id == str(work_item_id),
            WorkItem.import_id == batch.id,
        )
    )
    if item is None:
        raise HTTPException(404, "Excel work item not found", headers=NO_STORE)
    catalog = price_source(user)
    if catalog is None:
        raise HTTPException(409, "Install a verified PDF price list first", headers=NO_STORE)
    cilt1 = analysis_source(user)
    current = effective_item(db, item)
    match = discover_candidates(
        current.raw_description, current.normalized_unit, current.quantity,
        catalog, cilt1, input_review_required=current.review_required,
    )
    response.headers.update(NO_STORE)
    return {
        "read_only": True, "approval_allowed": False, "cost_allowed": False,
        "catalog_matching_performed": True,
        "candidate_selected": False,
        "excel": {
            "source_sha256": batch.sha256, "sheet_name": batch.sheet_name,
            "source_row": item.source_row, "work_item_id": item.id,
            "revision_id": current.revision_id, "description": current.raw_description,
        },
        "catalog": {
            "edition_date": catalog["edition_date"],
            "source_sha256": catalog["source_sha256"],
            "position_count": len(catalog["records"]),
            "analysis_source_sha256": cilt1["source_sha256"] if cilt1 else None,
        },
        **match,
    }
