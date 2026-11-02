"""A3.45: source-bound, independently signed, read-only partial cost preview.

The A318/A330 workflow is deliberately NOT represented as M5 estimate approval.
A source candidate, precheck, pilot acknowledgement, or saved analysis alone
never creates a priced line. Pending rows do not block valid independent rows.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .a318_pdf_api import _read as pdf_source
from .a330_editable_analysis import (
    ProposedLine, _calculations, _latest_revision, _latest_signoff, _source as verified_source,
)
from .a330_review_store import VerifiedEngineeringReviewer
from .database import get_db
from .models import User, WorkItem
from .revisions import effective_item
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a345/imports/{import_id}",
    tags=["A3.45 Source-bound Cost Preview"],
)
CENT = Decimal("0.01")


def _validated_analysis_price(revision) -> Decimal:
    """Recompute persisted line data; never trust a stored total alone.

    A3.30 already adds the 25% overhead/profit ONCE to the item subtotal.
    Never add 25% again to a stored proposed_amount or a source PDF price.
    """
    raw = json.loads(revision.items_json)
    lines = [ProposedLine(**{
        name: item[name]
        for name in ("code", "description", "unit", "quantity", "unit_price")
    }) for item in raw]
    _, expected = _calculations(lines)
    stored = Decimal(revision.proposed_amount)
    if stored <= 0 or stored != Decimal(expected):
        raise ValueError("Proposed analysis total does not match its inputs")
    return stored


def _signed_review_current(db: Session, signed_by_id: str) -> bool:
    reviewer = db.get(User, signed_by_id)
    credential = db.get(VerifiedEngineeringReviewer, signed_by_id)
    return bool(
        reviewer and reviewer.role == "engineer" and credential
        and credential.verified_by_id != signed_by_id
        and credential.verification_reference.strip()
    )


@router.get("/cost-preview")
def partial_cost_preview(
    project_id: UUID, import_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    batch = _source(db, user, str(project_id), str(import_id))
    found = pdf_source(user)
    if found is None:
        raise HTTPException(409, "Connect the current analysis PDF before cost preview")
    digest, _ = found
    items = db.scalars(select(WorkItem).where(
        WorkItem.import_id == batch.id
    ).order_by(WorkItem.source_row, WorkItem.id)).all()
    included: list[dict] = []
    pending: list[dict] = []
    total = Decimal("0")

    for item in items:
        current = effective_item(db, item)
        why = None
        latest = _latest_revision(db, item.id)
        signoff = _latest_signoff(db, item.id)
        if not signoff or signoff.action != "approve":
            why = "Mühendis teknik onayı bekleniyor"
        elif not latest:
            why = "Kaydedilmiş analiz bulunamadı"
        elif not _signed_review_current(db, signoff.signed_by_id):
            why = "Geçerli bağımsız mühendis yetkisi doğrulanamadı"
        elif current.review_required or current.quantity is None or current.quantity <= 0:
            why = "Metraj miktarı veya giriş bilgisi doğrulanmalı"
        elif not current.normalized_unit:
            why = "Metraj ölçü birimi eksik"
        else:
            try:
                row, fingerprint, position, source_sha = verified_source(
                    db, user, project_id, import_id, UUID(item.id)
                )
                if (
                    source_sha != digest or row["status"] != "documented_for_review"
                    or not position.price_verified
                    or current.normalized_unit != position.unit
                    or latest.source_fingerprint != fingerprint
                    or latest.analysis_pdf_sha256 != digest
                    or latest.candidate_code != position.id
                    or signoff.source_fingerprint != fingerprint
                    or signoff.analysis_revision_id != latest.id
                    or signoff.import_id != batch.id
                    or signoff.project_id != batch.project_id
                ):
                    why = "Analiz, poz, kaynak veya teknik kanıt yeniden doğrulanmalı"
                else:
                    price = _validated_analysis_price(latest)
                    quantity = Decimal(str(current.quantity))
                    amount = (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
                    included.append({
                        "work_item_id": item.id, "source_row": item.source_row,
                        "description": current.raw_description, "position_code": position.id,
                        "quantity": str(quantity), "unit": current.normalized_unit,
                        "unit_price": str(price), "amount": str(amount),
                        "source_pdf_sha256": digest, "source_pdf_page": position.pdf_page,
                        "analysis_revision_id": latest.id, "signoff_id": signoff.id,
                        "price_basis": "engineer_approved_project_analysis",
                    })
                    total += amount
            except (HTTPException, ValueError, InvalidOperation, KeyError, TypeError):
                why = "Güncel PDF/şartname kanıtı veya analiz tutarı doğrulanamadı"
        if why:
            pending.append({
                "work_item_id": item.id, "source_row": item.source_row,
                "description": current.raw_description, "reason": why,
                "amount": None,
            })

    response.headers.update(NO_STORE)
    return {
        "schema": "arkemx.a345.partial_cost_preview.v1",
        "read_only": True, "creates_estimate": False,
        "source_pdf_sha256": digest,
        "import_id": batch.id, "import_sha256": batch.sha256,
        "total_rows": len(items),
        "included_count": len(included), "pending_count": len(pending),
        "is_partial": bool(pending),
        "partial_total": str(total.quantize(CENT, rounding=ROUND_HALF_UP)),
        "currency": "TRY", "included": included, "pending": pending,
        "note": (
            "Read-only engineering-approved project analysis preview, not an M5 estimate. "
            "Pending rows are excluded, not priced at zero. VAT and other project charges are excluded."
        ),
    }
