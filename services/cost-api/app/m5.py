"""M5.0 draft cost estimates.

Prices are supplied manually with provenance; never read third-party catalog prices
for billable output. Only fresh, technically compatible and human-approved
candidate/position pairs may enter immutable estimate snapshots.
"""
import csv
import hashlib
import io
import json
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from itertools import product
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .security import current_user
from .models import (
    User, MatchCandidate, MatchDecision, MatchRunItemSnapshot, WorkItem,
    CatalogPosition, ImportBatch, TechnicalEvidence, CostEstimate, CostEstimateLine
)
from .m42 import _context, _proof, _latest_decision_id
from .m43 import guard_no_active
from .revisions import effective_item, fingerprint, previously_frozen

router = APIRouter(prefix="/api/projects/{project_id}/m5", tags=["M5 Draft Cost Estimates"])
CENT = Decimal("0.01")
SCALE_4 = Decimal("0.0001")
MAX_LEGACY_PRICE_FORMATS = 625  # bounded, one-time read of pre-fix snapshots
MAX_LINES = 500


class PriceLine(BaseModel):
    candidate_id: str = Field(min_length=36, max_length=36)
    unit_price: str = Field(pattern=r"^[0-9]{1,9}(\.[0-9]{1,4})?$")
    price_source: str = Field(min_length=10, max_length=200)


class EstimateRequest(BaseModel):
    run_id: str = Field(min_length=36, max_length=36)
    request_key: str = Field(min_length=12, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    title: str = Field(min_length=3, max_length=160)
    lines: list[PriceLine] = Field(min_length=1, max_length=MAX_LINES)


def _sha(obj: object) -> str:
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fixed4(value: Decimal) -> str:
    # Numeric(18, 4) stored in SQL: use the exact same representation pre/post DB read.
    return format(value.quantize(SCALE_4), ".4f")


def _verify_legacy_price_scales(canonical: list[dict], expected_hash: str) -> bool:
    """Pre-fix drafts hashed user-typed price strings rather than Numeric(18, 4).
    
    Recover *only* numerically equivalent 0..4 decimal spellings. Every
    other field (candidate, quantity, position, evidence, source, amount)
    stays unchanged. The stored original SHA must still match exactly.
    Limit combinations to avoid unbounded legacy verification for large jobs.
    """
    alternatives = []
    combinations = 1
    for row in canonical:
        stored = Decimal(row["unit_price"])
        options = []
        for decimals in range(5):
            candidate = format(stored, f".{decimals}f")
            if Decimal(candidate) == stored:
                options.append(candidate)
        combinations *= len(options)
        if combinations > MAX_LEGACY_PRICE_FORMATS:
            return False
        alternatives.append(options)
    for prices in product(*alternatives):
        legacy_rows = [
            {**row, "unit_price": price}
            for row, price in zip(canonical, prices)
        ]
        if _sha(legacy_rows) == expected_hash:
            return True
    return False


def _snapshot(db: Session, user: User, project_id: str):
    context = _context(db, user, project_id)  # tenant isolation, rights and latest completed M4 run
    if context is None:
        raise HTTPException(409, "M4.1/M4.3 teknik kanitli calisma gerekli")
    run, version, source, rights_active, outdated = context
    if not rights_active:
        raise HTTPException(403, "Katalog eslestirme hakki aktif degil")
    if outdated:
        raise HTTPException(409, "Metraj degisti; once yeni teknik karsilastirma yapin")
    guard_no_active(db, project_id)
    imported = db.get(ImportBatch, run.import_id)
    if not imported:
        raise HTTPException(409, "Kaynak metraj bulunamadi")

    rows = db.execute(
        select(MatchCandidate, MatchRunItemSnapshot, WorkItem, CatalogPosition,
               TechnicalEvidence, MatchDecision)
        .join(MatchRunItemSnapshot,
              (MatchRunItemSnapshot.run_id == MatchCandidate.run_id) &
              (MatchRunItemSnapshot.work_item_id == MatchCandidate.work_item_id))
        .join(WorkItem, WorkItem.id == MatchCandidate.work_item_id)
        .join(CatalogPosition, CatalogPosition.id == MatchCandidate.position_id)
        .outerjoin(TechnicalEvidence, TechnicalEvidence.candidate_id == MatchCandidate.id)
        .outerjoin(MatchDecision, MatchDecision.id == _latest_decision_id())
        .where(MatchCandidate.run_id == run.id)
        .order_by(WorkItem.source_row, MatchCandidate.id)
    ).all()
    eligible = {}
    for candidate, snap, item, position, evidence, decision in rows:
        if not decision or decision.action != "approve":
            continue
        # Tampered evidence fails closed, it cannot be silently omitted.
        proof = _proof(evidence)
        if (not proof or proof["status"] != "compatible" or not candidate.approvable
                or snap.review_required or snap.quantity is None or snap.quantity <= 0):
            raise HTTPException(409, "Onayli pozda teknik veya miktar sorunu var")
        if fingerprint(effective_item(db, item)) != previously_frozen(item, snap):
            raise HTTPException(409, "Onaydan sonra metraj revize edildi")
        if snap.unit != position.unit:
            raise HTTPException(409, "Metraj ve poz birimleri uyusmuyor")
        eligible[candidate.id] = {
            "candidate_id": candidate.id, "work_item_id": item.id,
            "position_id": position.id, "source_row": item.source_row,
            "description": snap.description, "position_code": position.code,
            "unit": snap.unit, "quantity": Decimal(str(snap.quantity)),
            "evidence_sha256": evidence.evidence_sha256
        }
    return run, version, imported, eligible


def _display(row):
    return {**row, "quantity": str(row["quantity"])}


@router.get("/eligible")
def eligible_lines(project_id: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    run, version, imported, eligible = _snapshot(db, user, project_id)
    return {
        "run_id": run.id, "currency": "TRY", "row_count": run.row_count,
        "source_file_sha256": imported.sha256, "catalog_sha256": version.sha256,
        "eligible_count": len(eligible),
        "items": [_display(v) for v in eligible.values()],
        "note": "Yalniz muhendis onayli pozlar. Birim fiyatlar elle ve kaynak aciklamasiyla girilir."
    }


def _estimate_view(e: CostEstimate):
    return {"id": e.id, "project_id": e.project_id, "run_id": e.run_id,
            "title": e.title, "currency": e.currency,
            "total": str(e.total), "line_count": e.line_count,
            "source_file_sha256": e.source_file_sha256,
            "catalog_sha256": e.catalog_sha256, "snapshot_sha256": e.snapshot_sha256,
            "created_at": e.created_at, "status": "draft",
            "official_prices": False, "human_approval_required": True}


def _owned(db: Session, user: User, project_id: str, estimate_id: str):
    from .m2 import tenant_project
    tenant_project(db, user, project_id)
    estimate = db.scalar(select(CostEstimate).where(
        CostEstimate.id == estimate_id, CostEstimate.project_id == project_id,
        CostEstimate.organization_id == user.organization_id))
    if not estimate:
        raise HTTPException(404, "Taslak bulunamadi")
    return estimate


@router.get("/estimates")
def list_estimates(project_id: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    from .m2 import tenant_project
    tenant_project(db, user, project_id)
    estimates = db.scalars(select(CostEstimate).where(
        CostEstimate.project_id == project_id,
        CostEstimate.organization_id == user.organization_id
    ).order_by(CostEstimate.created_at.desc(), CostEstimate.id.desc()).limit(50)).all()
    return [_estimate_view(e) for e in estimates]


@router.get("/estimates/{estimate_id}")
def get_estimate(project_id: str, estimate_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    estimate = _owned(db, user, project_id, estimate_id)
    items = db.scalars(select(CostEstimateLine).where(
        CostEstimateLine.estimate_id == estimate.id
    ).order_by(CostEstimateLine.source_row, CostEstimateLine.position_code)).all()
    canonical = [{
        "candidate_id": line.candidate_id, "description": line.description,
        "source_row": line.source_row, "quantity": str(line.quantity),
        "unit": line.unit, "position_code": line.position_code,
        "unit_price": str(line.unit_price), "amount": str(line.amount),
        "price_source": line.price_source, "evidence_sha256": line.evidence_sha256
    } for line in items]
    # Always check arithmetic and exact stored-line count before any legacy compatibility.
    if (len(items) != estimate.line_count or
            _money(sum((line.amount for line in items), Decimal("0"))) != estimate.total or
            any(_money(line.quantity * line.unit_price) != line.amount for line in items)):
        raise HTTPException(409, "Maliyet taslagi hesap veya kanit butunlugu bozulmus")
    if (_sha(canonical) != estimate.snapshot_sha256 and
            not _verify_legacy_price_scales(canonical, estimate.snapshot_sha256)):
        raise HTTPException(409, "Maliyet taslagi hesap veya kanit butunlugu bozulmus")
    return {**_estimate_view(estimate), "lines": [
        {"candidate_id": line.candidate_id, "work_item_id": line.work_item_id,
         "source_row": line.source_row, "description": line.description,
         "position_code": line.position_code, "unit": line.unit,
         "quantity": str(line.quantity), "unit_price": str(line.unit_price),
         "amount": str(line.amount), "price_source": line.price_source,
         "evidence_sha256": line.evidence_sha256} for line in items]}


@router.post("/estimates", status_code=201)
def create_estimate(project_id: str, payload: EstimateRequest,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .m2 import tenant_project
    tenant_project(db, user, project_id)
    digest = _sha(payload.model_dump())
    existing = db.scalar(select(CostEstimate).where(
        CostEstimate.project_id == project_id, CostEstimate.request_key == payload.request_key))
    if existing:
        if existing.request_sha256 != digest:
            raise HTTPException(409, "Ayni istek anahtari farkli veriler icin kullanilamaz")
        return _estimate_view(existing)

    if len(payload.title.strip()) < 3:
        raise HTTPException(422, "Baslik en az 3 anlamli karakter olmalidir")
    if any(len(line.price_source.strip()) < 10 for line in payload.lines):
        raise HTTPException(422, "Fiyat kaynagi aciklamasi en az 10 karakter olmalidir")
    run, version, imported, eligible = _snapshot(db, user, project_id)
    if payload.run_id != run.id:
        raise HTTPException(409, "Maliyet yalniz guncel teknik calismaya baglanabilir")
    if not eligible:
        raise HTTPException(409, "Maliyet icin muhendis onayli poz bulunamadi")
    seen_items = set()
    seen_candidates = set()
    entries = []
    total = Decimal("0")
    for entry in payload.lines:
        row = eligible.get(entry.candidate_id)
        if not row:
            raise HTTPException(409, "Poz guncel muhendis onayinda degil")
        if row["work_item_id"] in seen_items or row["candidate_id"] in seen_candidates:
            raise HTTPException(409, "Bir metraj kalemi bir taslakta yalniz bir kez fiyatlanabilir")
        seen_items.add(row["work_item_id"])
        seen_candidates.add(row["candidate_id"])
        try:
            unit_price = Decimal(entry.unit_price)
        except InvalidOperation:
            raise HTTPException(422, "Gecersiz fiyat") from None
        if not unit_price.is_finite() or unit_price <= 0:
            raise HTTPException(422, "Birim fiyat pozitif olmalidir")
        amount = _money(row["quantity"] * unit_price)
        total += amount
        entries.append((row, unit_price, amount, entry.price_source.strip()))
    # Canonical deterministic digest of frozen input and manual pricing.
    canonical = [{"candidate_id": r["candidate_id"], "description": r["description"],
                  "source_row": r["source_row"], "quantity": _fixed4(r["quantity"]),
                  "unit": r["unit"], "position_code": r["position_code"],
                  "unit_price": _fixed4(p), "amount": str(a),
                  "price_source": label, "evidence_sha256": r["evidence_sha256"]}
                 for r, p, a, label in sorted(entries, key=lambda e: (e[0]["source_row"], e[0]["candidate_id"]))]
    estimate = CostEstimate(
        organization_id=user.organization_id, project_id=project_id, run_id=run.id,
        import_id=imported.id, version_id=run.version_id,
        created_by_id=user.id, request_key=payload.request_key, request_sha256=digest,
        title=payload.title.strip(), currency="TRY", total=_money(total),
        line_count=len(entries), source_file_sha256=imported.sha256,
        catalog_sha256=version.sha256, snapshot_sha256=_sha(canonical)
    )
    db.add(estimate)
    db.flush()
    for row, price, amount, label in entries:
        db.add(CostEstimateLine(
            estimate_id=estimate.id, candidate_id=row["candidate_id"],
            work_item_id=row["work_item_id"], position_id=row["position_id"],
            source_row=row["source_row"], description=row["description"],
            position_code=row["position_code"], unit=row["unit"],
            quantity=row["quantity"], unit_price=price, amount=amount,
            price_source=label, evidence_sha256=row["evidence_sha256"]))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(CostEstimate).where(
            CostEstimate.project_id == project_id, CostEstimate.request_key == payload.request_key))
        if prior and prior.request_sha256 == digest:
            return _estimate_view(prior)
        raise HTTPException(409, "Taslak kayit cakismasi") from None
    return _estimate_view(estimate)


def _csv_safe(value) -> str:
    text = str(value or "")
    # Spreadsheet formula injection from untrusted work descriptions/source labels.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


@router.get("/estimates/{estimate_id}/csv")
def download_csv(project_id: str, estimate_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    estimate = get_estimate(project_id, estimate_id, user, db)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["ARKEMX M5 - TASLAK MALIYET", _csv_safe(estimate["title"]), "TRY"])
    writer.writerow(["Kaynak Excel SHA-256", estimate["source_file_sha256"]])
    writer.writerow(["Katalog SHA-256", estimate["catalog_sha256"]])
    writer.writerow(["Taslak SHA-256", estimate["snapshot_sha256"]])
    writer.writerow(["Satir", "Imalat", "Poz", "Birim", "Miktar", "Birim Fiyat", "Tutar", "Fiyat Kaynagi"])
    for line in estimate["lines"]:
        writer.writerow([line["source_row"], _csv_safe(line["description"]),
            _csv_safe(line["position_code"]), _csv_safe(line["unit"]),
            line["quantity"], line["unit_price"], line["amount"], _csv_safe(line["price_source"])])
    writer.writerow(["", "", "", "", "", "TOPLAM", estimate["total"], "TRY"])
    writer.writerow(["NOT", "Bu belge teklif degildir. Resmi birim fiyatlar otomatik kullanilmamistir."])
    return Response(content="\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="arkemx-m5-{estimate_id}.csv"',
                             "Cache-Control": "no-store"})
