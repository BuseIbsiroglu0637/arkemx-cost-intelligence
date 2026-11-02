"""A3.49.1 — conservative, source-bound understanding of architect Excel descriptions.

This is NOT a position matcher, trained AI model, technical compliance checker,
engineering approval, or price calculation. It uses existing A1/A3 extraction
rules and never writes to source metraj or the 2026 PDF catalog.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a347_spec_completion import work_scope
from .database import get_db
from .excel import normalized
from .models import User, WorkItem
from .measurement_context import extract_measurements
from .revisions import effective_item
from .security import current_user
from .technical import extract
from .technical_analysis.layers import extract_layer_measurements, extract_work_scopes

router = APIRouter(
    prefix="/api/projects/{project_id}/a349",
    tags=["A3.49.1 Read-only Metraj Understanding"],
)
VERSION = "a3491-rules-v1"
FAMILIES = {
    "gazbeton": r"\bgazbeton\b",
    "siva": r"\bsiva\w*\b",
    "seramik": r"\b(?:seramik\w*|porselen\w*|karo\w*|fayans\w*)\b",
    "pvc": r"\bpvc\b",
    "boya": r"\b(?:boya\w*|boyan\w*)\b",
    "beton": r"\bbeton\b",
    "tugla": r"\btugla\b",
    "celik": r"\bcelik\b",
    "ahsap": r"\bahsap\b",
    "yalitim": r"\byalitim\b",
}
BINDERS = {
    "cimento": r"\bcimento\b",
    "alci": r"\balci\b",
    "kirec": r"\bkirec\b",
}
# Identifying the explicit scope is deliberately separate from inferring
# whether a public poz includes labor, materials, demolition or equipment.
NEGATED_OR_UNCERTAIN = re.compile(
    r"\b(?:haric|dahil\s+degil|kapsam\s+disi|yapilmayacak|uygulanmayacak)\b"
)
MAX_PREVIEW = 100


def _named(text: str, patterns: dict[str, str]) -> list[str]:
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]


def _str_decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def describe_metraj(
    description: str, unit: str | None, quantity: Decimal | None,
    *, input_review_required: bool = False,
) -> dict:
    """Inspect only information explicitly present in an Excel metraj row.

    Source text stays verbatim. A 60x60 cm size is NOT a thickness; concrete
    N/mm2, density kg/m3 and grout mm do not become wall thickness.
    """
    raw = description or ""
    plain = normalized(raw)
    found_families = _named(plain, FAMILIES)
    binders = _named(plain, BINDERS)
    technical = extract(raw, unit)
    # A1's broad mm/cm lexer can see a 60x60 cm tile size or 3 mm grout
    # even in a clause mentioning plaster. Validate every measured layer
    # against the independent dimension/joint-aware parser before using it.
    thickness_candidates = extract_measurements(raw, ceramic=False)["thickness_mm"]
    explicit_layers = tuple(
        layer for layer in extract_layer_measurements(raw)
        if layer.work_type is not None
        and (layer.thickness_mm is None
             or round(float(layer.thickness_mm), 3) in thickness_candidates)
    )
    layers = [
        {
            "work_type": layer.work_type,
            "thickness_mm": _str_decimal(layer.thickness_mm),
            "materials": list(layer.materials),
            "evidence": {
                "quote": layer.quote,
                "start": layer.start,
                "end": layer.end,
                "offset_basis": "original_excel_description",
            },
        }
        for layer in explicit_layers
    ]
    # The A1 layer extractor is narrower than generic work families and
    # cannot recognize PVC, ceramics or dimensions as plaster layers.
    # Keep explicit technical dimensions as a separate set of facts.
    layer_types = {layer["work_type"] for layer in layers if layer["work_type"]}
    multiple_work_types = len(layer_types) > 1 or (
        len(found_families) > 1 and
        not (set(found_families) <= {"seramik", "pvc"})
    )
    measurements = sorted({
        layer["thickness_mm"] for layer in layers
        if layer["thickness_mm"] is not None
    })
    if not measurements and technical["thickness_mm"] is not None:
        measurements = [str(technical["thickness_mm"])]
    scope = work_scope(raw)
    explicit_scopes = extract_work_scopes(raw)
    flags: list[str] = []
    if not plain:
        flags.append("DESCRIPTION_MISSING")
    elif not found_families:
        flags.append("MATERIAL_FAMILY_UNRECOGNIZED")
    if not unit:
        flags.append("UNIT_MISSING")
    if quantity is None:
        flags.append("QUANTITY_MISSING")
    if input_review_required:
        flags.append("METRAJ_INPUT_REVIEW_REQUIRED")
    if multiple_work_types:
        flags.append("MULTIPLE_WORK_TYPES")
    if len(binders) > 1 and not multiple_work_types:
        flags.append("MATERIAL_BINDER_AMBIGUOUS")
    if (len(explicit_layers) > 1 and
            any(layer["thickness_mm"] is None or layer["work_type"] is None for layer in layers)):
        flags.append("LAYER_ASSOCIATION_UNCERTAIN")
    if technical["thickness_mm"] is None and not measurements:
        # No thickness does not by itself mean the material is unusable:
        # never invent a mandatory thickness for every family.
        pass
    if NEGATED_OR_UNCERTAIN.search(plain) and scope == "unspecified":
        flags.append("WORK_SCOPE_UNCLEAR")
    if (len(explicit_layers) > 1 and not multiple_work_types and
            len(measurements) > 1):
        flags.append("THICKNESS_CONTEXT_UNCERTAIN")
    flags = sorted(set(flags))
    status = (
        "insufficient_input" if "DESCRIPTION_MISSING" in flags else
        "multiple_works_for_review" if multiple_work_types else
        "needs_review" if flags else "structured_for_retrieval"
    )
    return {
        "version": VERSION,
        "status": status,
        "description": raw,
        "source_text": raw,
        "unit": unit,
        "quantity": _str_decimal(quantity),
        "material_families": found_families,
        "material_family": found_families[0] if len(found_families) == 1 else None,
        "binder_materials": binders,
        "work_scope": scope,
        "layer_work_scopes": explicit_scopes,
        "layers": layers,
        "thicknesses_mm": measurements,
        "technical_facts": {
            "surface": technical["surface"],
            "method": technical["method"],
            "environment": technical["environment"],
            "dimensions": technical["dimensions"],
            "joint_width_mm": technical["joint_width_mm"],
            "gazbeton_strength_n_mm2": technical["gazbeton_strength_n_mm2"],
            "gazbeton_density_kg_m3": technical["gazbeton_density_kg_m3"],
        },
        "review_flags": flags,
        "technical_approved": False,
        "approval_allowed": False,
        "match_selected": False,
        "cost_allowed": False,
    }


@router.get("/imports/{import_id}/understanding")
def understand_metraj_import(
    project_id: UUID,
    import_id: UUID,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: Annotated[int, Query(ge=0, le=2000)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PREVIEW)] = 25,
):
    """Preview Excel rows; no catalog matching, no side effects, no approval."""
    batch = _source(db, user, str(project_id), str(import_id))
    count = db.scalar(select(func.count(WorkItem.id)).where(WorkItem.import_id == batch.id)) or 0
    items = db.scalars(
        select(WorkItem)
        .where(WorkItem.import_id == batch.id)
        .order_by(WorkItem.source_row, WorkItem.id)
        .offset(offset)
        .limit(limit)
    ).all()
    rows = []
    for original in items:
        current = effective_item(db, original)
        facts = describe_metraj(
            current.raw_description, current.normalized_unit, current.quantity,
            input_review_required=current.review_required,
        )
        rows.append({
            "work_item_id": original.id,
            "source_row": original.source_row,
            "sheet_name": batch.sheet_name,
            "revision_id": current.revision_id,
            "revision": current.revision,
            "source_is_revision": current.revision_id is not None,
            "understanding": facts,
        })
    response.headers.update(NO_STORE)
    return {
        "version": VERSION,
        "read_only": True,
        "source": {
            "project_id": batch.project_id, "import_id": batch.id,
            "excel_sha256": batch.sha256,
            "sheet_name": batch.sheet_name,
        },
        "total_rows": count,
        "offset": offset, "limit": limit, "returned": len(rows),
        "has_more": offset + len(rows) < count,
        "approval_allowed": False, "cost_allowed": False,
        "catalog_matching_performed": False,
        "rows": rows,
    }
