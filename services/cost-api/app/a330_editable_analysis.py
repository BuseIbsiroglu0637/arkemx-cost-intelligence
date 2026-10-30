"""A3.30: editable *proposals* and source-bound qualified engineering decisions.

Original PDFs, official rates and M5 approvals are never changed here.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source as tenant_source
from .a318_pdf_api import _pdf_candidate_check, _read as read_analysis
from .a327_decisions import _current
from .a330_review_store import (
    EngineeringSignoff, ProposedAnalysisRevision, VerifiedEngineeringReviewer,
)
from .database import get_db
from .models import PdfCandidateSelection, User, WorkItem
from .revisions import effective_item
from .security import current_user

router = APIRouter(
    prefix="/api/projects/{project_id}/a330/imports/{import_id}/items/{work_item_id}",
    tags=["A3.30 Source-Bound Engineering Review"],
)
MONEY = Decimal("0.01")
THICK = Decimal("0.0001")
SOURCE_LINE_LIMIT = 30
NUMBER = re.compile(r"^\\d{1,9}(?:[.,]\\d{1,4})?$".replace("\\\\", "\\"))
# Thousands are valid only with an explicit comma decimal marker, avoiding
# misreading ambiguous "1.234" as either 1.234 or 1234.
GROUPED_NUMBER = re.compile(r"^\\d{1,3}(?:\\.\\d{3})+(?:,\\d{1,4})$".replace("\\\\", "\\"))


class ProposedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=80)
    # The verified source-PDF parser can return an empty material description
    # while still providing its code, quantity, unit, unit price and amount.
    # Do not invent a material name or block saving a faithful source draft.
    description: str = Field(max_length=250)
    unit: str = Field(min_length=1, max_length=30)
    quantity: str
    unit_price: str

    @field_validator("code", "unit")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Invalid item field")
        return value

    @field_validator("description")
    @classmethod
    def preserve_missing_source_description(cls, value: str) -> str:
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid description")
        return value


class SaveProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ProposedLine] = Field(min_length=1, max_length=SOURCE_LINE_LIMIT)
    reason: str = Field(default="", max_length=1000)
    expected_source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_previous_revision_id: UUID | None
    request_key: UUID

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, text: str) -> str:
        return text.strip()


class SignoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    reason: str = Field(default="", max_length=1000)
    expected_source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_analysis_revision_id: UUID
    expected_previous_signoff_id: UUID | None
    request_key: UUID
    attestation: Literal["I_AM_VERIFIED_ENGINEER_AND_REVIEWED_EVIDENCE"]

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


def _number(value: str, scale: Decimal) -> Decimal:
    raw = value.strip()
    if GROUPED_NUMBER.fullmatch(raw):
        normalized = raw.replace(".", "").replace(",", ".")
    elif NUMBER.fullmatch(raw):
        normalized = raw.replace(",", ".")
    else:
        raise HTTPException(422, "Enter a positive decimal number (e.g. 1,03 or 1.250,00)")
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        raise HTTPException(422, "Invalid decimal input") from None
    if number <= 0 or number.as_tuple().exponent < scale.as_tuple().exponent:
        raise HTTPException(422, "Quantity/price must be positive and precision limited")
    return number


def _calculations(items: list[ProposedLine]) -> tuple[list[dict], str]:
    result = []
    total = Decimal("0")
    for item in items:
        qty = _number(item.quantity, THICK)
        unit_price = _number(item.unit_price, MONEY)
        amount = (qty * unit_price).quantize(MONEY, rounding=ROUND_HALF_UP)
        total += amount
        result.append({
            "code": item.code, "description": item.description, "unit": item.unit,
            "quantity": str(qty), "unit_price": str(unit_price),
            "amount": str(amount), "entry_type": "user_proposal",
        })
    # This reflects a proposed estimate formula, not an official price.
    proposal = (total * Decimal("1.25")).quantize(MONEY, rounding=ROUND_HALF_UP)
    return result, str(proposal)


def _source(db, user, project_id, import_id, item_id):
    batch = tenant_source(db, user, str(project_id), str(import_id))
    item = db.scalar(select(WorkItem).where(
        WorkItem.id == str(item_id), WorkItem.import_id == batch.id,
    ).with_for_update())
    if item is None:
        raise HTTPException(404, "Metraj row not found")
    current = effective_item(db, item)
    saved = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.organization_id == user.organization_id,
        PdfCandidateSelection.project_id == batch.project_id,
        PdfCandidateSelection.import_id == batch.id,
        PdfCandidateSelection.work_item_id == item.id,
    ))
    found = read_analysis(user)
    if not saved or not found:
        raise HTTPException(409, "Save an analysis PDF position first")
    digest, catalog = found
    if saved.pdf_sha256 != digest or saved.revision_id != current.revision_id:
        raise HTTPException(409, "Source or metraj revision changed; reselect the position")
    position = next((p for p in catalog if p.id == saved.position_code), None)
    if not position or _pdf_candidate_check(current, position)["status"] == "blocked":
        raise HTTPException(409, "Saved position is missing or technically blocked")
    row, fingerprint = _current(db, user, project_id, import_id, item_id)
    if row["saved_candidate"] != position.id:
        raise HTTPException(409, "Saved position not verified against current sources")
    return row, fingerprint, position, digest


def _latest_revision(db: Session, item_id: str):
    return db.scalar(select(ProposedAnalysisRevision).where(
        ProposedAnalysisRevision.work_item_id == item_id,
    ).order_by(ProposedAnalysisRevision.version.desc()).limit(1))


def _latest_signoff(db: Session, item_id: str):
    return db.scalar(select(EngineeringSignoff).where(
        EngineeringSignoff.work_item_id == item_id,
    ).order_by(EngineeringSignoff.created_at.desc(),
               EngineeringSignoff.id.desc()).limit(1))


def _engineer_eligible(db: Session, user: User) -> bool:
    credential = db.get(VerifiedEngineeringReviewer, user.id)
    return bool(
        user.role == "engineer" and credential is not None
        and credential.verified_by_id != user.id
        and credential.verification_reference.strip()
    )


def _serialize_revision(revision: ProposedAnalysisRevision, fingerprint: str) -> dict:
    return {
        "id": revision.id, "version": revision.version,
        "items": json.loads(revision.items_json),
        "reason": revision.reason, "proposed_amount": revision.proposed_amount,
        "source_current": revision.source_fingerprint == fingerprint,
        "created_by_id": revision.created_by_id, "created_at": revision.created_at,
    }


def _fingerprint_request(payload, user, project_id, item_id):
    data = {**payload.model_dump(mode="json"), "user_id": user.id,
            "project_id": str(project_id), "work_item_id": str(item_id)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _signoff_state(db, work_id, fingerprint, latest):
    signoff = _latest_signoff(db, work_id)
    valid = bool(signoff and latest and signoff.source_fingerprint == fingerprint
                 and signoff.analysis_revision_id == latest.id
                 and signoff.action == "approve")
    return {
        "engineering_approved": valid,
        "review": ({
            "id": signoff.id, "action": signoff.action,
            "source_current": signoff.source_fingerprint == fingerprint
            and latest is not None and signoff.analysis_revision_id == latest.id,
            "signed_by_id": signoff.signed_by_id, "created_at": signoff.created_at,
            "reason": signoff.reason,
        } if signoff else None),
    }


@router.get("/analysis")
def analysis_state(
    project_id: UUID, import_id: UUID, work_item_id: UUID, response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint, position, digest = _source(
        db, user, project_id, import_id, work_item_id,
    )
    latest = _latest_revision(db, str(work_item_id))
    response.headers.update(NO_STORE)
    return {
        "work_item_id": str(work_item_id), "candidate_code": position.id,
        "source_fingerprint": fingerprint, "pdf_sha256": digest,
        "pdf_page": position.pdf_page, "pdf_price": str(position.price),
        "pdf_price_verified": position.price_verified,
        "source_inputs": position.ingredients,
        "latest_revision": _serialize_revision(latest, fingerprint) if latest else None,
        "read_only_source": True,
        "engineering": {
            **_signoff_state(db, str(work_item_id), fingerprint, latest),
            "reviewer_eligible": _engineer_eligible(db, user),
            "evidence_ready": row["status"] == "documented_for_review",
            "cost_allowed": False,
        },
    }


@router.post("/analysis/revisions", status_code=201)
def save_analysis_revision(
    project_id: UUID, import_id: UUID, work_item_id: UUID, payload: SaveProposal,
    response: Response, user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint, position, digest = _source(
        db, user, project_id, import_id, work_item_id,
    )
    request_hash = _fingerprint_request(payload, user, project_id, work_item_id)
    old = db.scalar(select(ProposedAnalysisRevision).where(
        ProposedAnalysisRevision.organization_id == user.organization_id,
        ProposedAnalysisRevision.project_id == str(project_id),
        ProposedAnalysisRevision.request_key == str(payload.request_key),
    ))
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, "Request key already used")
        response.status_code = 200
        response.headers.update(NO_STORE)
        return _serialize_revision(old, fingerprint)
    if fingerprint != payload.expected_source_fingerprint:
        raise HTTPException(409, "Document or position source changed; reload")
    previous = _latest_revision(db, str(work_item_id))
    expected = str(payload.expected_previous_revision_id) if payload.expected_previous_revision_id else None
    if expected != (previous.id if previous else None):
        raise HTTPException(409, "Analysis revision changed; reload")
    lines, proposal = _calculations(payload.items)
    revision = ProposedAnalysisRevision(
        organization_id=user.organization_id, project_id=str(project_id),
        import_id=str(import_id), work_item_id=str(work_item_id),
        version=(previous.version + 1 if previous else 1),
        candidate_code=position.id, analysis_pdf_sha256=digest,
        source_fingerprint=fingerprint,
        items_json=json.dumps(lines, ensure_ascii=False),
        proposed_amount=proposal, reason=payload.reason or "Gerekçe belirtilmedi",
        created_by_id=user.id, request_key=str(payload.request_key),
        request_hash=request_hash,
    )
    db.add(revision)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent revision; reload") from None
    response.headers.update(NO_STORE)
    return _serialize_revision(revision, fingerprint)


@router.post("/engineering/signoff", status_code=201)
def record_engineering_signoff(
    project_id: UUID, import_id: UUID, work_item_id: UUID, payload: SignoffRequest,
    response: Response, user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row, fingerprint, position, digest = _source(
        db, user, project_id, import_id, work_item_id,
    )
    if not _engineer_eligible(db, user):
        raise HTTPException(403, "Independently verified engineer credentials are required")
    request_hash = _fingerprint_request(payload, user, project_id, work_item_id)
    existing = db.scalar(select(EngineeringSignoff).where(
        EngineeringSignoff.organization_id == user.organization_id,
        EngineeringSignoff.project_id == str(project_id),
        EngineeringSignoff.request_key == str(payload.request_key),
    ))
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Request key already used")
        response.status_code = 200
        response.headers.update(NO_STORE)
        return {"id": existing.id, "action": existing.action, "cost_allowed": False}
    latest = _latest_revision(db, str(work_item_id))
    if (not latest or latest.id != str(payload.expected_analysis_revision_id)
            or latest.source_fingerprint != fingerprint
            or fingerprint != payload.expected_source_fingerprint):
        raise HTTPException(409, "Analysis/source changed; reload")
    if payload.action == "approve" and (
        row["status"] != "documented_for_review"
        or not position.price_verified
    ):
        raise HTTPException(409, "Qualified evidence and verified PDF price are required")
    previous = _latest_signoff(db, str(work_item_id))
    expected = str(payload.expected_previous_signoff_id) if payload.expected_previous_signoff_id else None
    if expected != (previous.id if previous else None):
        raise HTTPException(409, "Engineering decision history changed; reload")
    entry = EngineeringSignoff(
        organization_id=user.organization_id, project_id=str(project_id),
        import_id=str(import_id), work_item_id=str(work_item_id),
        analysis_revision_id=latest.id, source_fingerprint=fingerprint,
        action=payload.action, reason=payload.reason or "Gerekçe belirtilmedi",
        signed_by_id=user.id, request_key=str(payload.request_key),
        request_hash=request_hash,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent engineering signoff; reload") from None
    response.headers.update(NO_STORE)
    return {
        "id": entry.id, "action": entry.action,
        "engineering_approved": entry.action == "approve",
        "cost_allowed": False,
    }
