"""Small source-attributed manual-price pilot, independent of M5 approvals.

All arithmetic and coverage are authoritative on the server. A user review is
never represented as engineering signoff or official-source verification.
"""
import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .a3_batch_review import NO_STORE, _source
from .database import get_db
from .import_policy import guard_source
from .m2 import tenant_project
from .m5 import _csv_safe
from .models import ImportBatch, User, WorkItem, WorkItemRevision
from .pilot_cost_store import PilotCostSnapshot
from .security import current_user

router = APIRouter(prefix="/api/projects/{project_id}/pilot-costs", tags=["Reviewed pilot costs"])
CENT = Decimal("0.01")
LIMIT = 500


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_id: UUID
    unit: str = Field(min_length=1, max_length=30)
    unit_price: str
    source: str = Field(min_length=10, max_length=500)
    source_date: date

    @field_validator("source")
    @classmethod
    def clean_source(cls, value):
        if len(value.strip()) < 10 or any(ord(c) < 32 for c in value):
            raise ValueError("Fiyat kaynağını belge/teklif ve sayfa veya satırla belirtin.")
        return value.strip()

    @field_validator("unit_price")
    @classmethod
    def price_number(cls, value):
        raw = value.strip()
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,4}", raw):
            raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,9}(?:[.,]\d{1,4})?", raw):
            # 1.234 is ambiguous in Turkish spreadsheets; never guess.
            if re.fullmatch(r"\d{1,3}\.\d{3}", raw):
                raise ValueError("Belirsiz fiyat: 1234,00 veya 1,2340 yazın.")
            raw = raw.replace(",", ".")
        else:
            raise ValueError("Geçerli, pozitif birim fiyat girin: 1250,50")
        amount = Decimal(raw)
        if not 0 < amount <= Decimal("999999999.9999"):
            raise ValueError("Birim fiyat sıfırdan büyük olmalı.")
        return format(amount.quantize(Decimal("0.0001")), "f")


class Calculation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_id: UUID
    prices: list[Price] = Field(default_factory=list, max_length=LIMIT)


class Save(Calculation):
    title: str = Field(min_length=3, max_length=160)
    expected_preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: UUID
    acknowledgement: Literal["I_REVIEWED_QUANTITIES_UNITS_AND_PRICE_SOURCES"]


def current_source(db, user, project_id, import_id=None):
    tenant_project(db, user, project_id)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id)
                      .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()).limit(1))
    if not batch:
        raise HTTPException(409, "Önce Metraj adımından bir Excel kaydedin.")
    if import_id is not None and str(import_id) != batch.id:
        raise HTTPException(409, "Excel kaynağı değişti. Güncel metrajı yeniden yükleyin.")
    guard_source(db, batch.id)
    _source(db, user, project_id, batch.id)
    items = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)
                       .order_by(WorkItem.source_row, WorkItem.id).limit(LIMIT + 1)).all()
    if not items or len(items) > LIMIT:
        raise HTTPException(422, "Küçük pilot 1–500 metraj satırı kabul eder; dosya bölünmeden toplam üretilmez.")
    revisions = db.scalars(select(WorkItemRevision).join(WorkItem)
                           .where(WorkItem.import_id == batch.id)
                           .order_by(WorkItemRevision.revision)).all()
    latest = {r.work_item_id: r for r in revisions}
    rows = []
    for item in items:
        rev = latest.get(item.id)
        quantity = rev.quantity if rev else item.quantity
        rows.append({"work_item_id": item.id, "source_row": item.source_row,
                     "revision_id": rev.id if rev else None,
                     "description": rev.description if rev else item.raw_description,
                     "quantity": format(Decimal(str(quantity)), ".4f") if quantity is not None else None,
                     "unit": rev.unit if rev else item.normalized_unit,
                     "review_required": False if rev else item.review_required})
    return batch, rows


@router.get("/source")
def source(project_id: str, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    batch, rows = current_source(db, user, project_id)
    response.headers.update(NO_STORE)
    return {"import_id": batch.id, "filename": batch.original_filename,
            "source_sha256": batch.sha256, "rows": rows}


def calculate(db, user, project_id, payload):
    batch, rows = current_source(db, user, project_id, payload.import_id)
    prices = {str(p.work_item_id): p for p in payload.prices}
    if len(prices) != len(payload.prices) or set(prices) - {r["work_item_id"] for r in rows}:
        raise HTTPException(422, "Tekrarlı veya bu Excel'e ait olmayan fiyat satırı.")
    total = Decimal("0.00")
    included = 0
    for row in rows:
        price = prices.get(row["work_item_id"])
        row.update(amount=None, unit_price=None, price_source=None, price_date=None)
        if row["review_required"] or not row["unit"] or row["quantity"] is None or Decimal(row["quantity"]) <= 0:
            row["reason"] = "Metraj miktarı/birimi için düzeltme gerekiyor"
        elif price is None:
            row["reason"] = "Kaynaklı birim fiyat eksik"
        elif price.unit != row["unit"]:
            raise HTTPException(422, f"Satır {row['source_row']}: fiyat birimi metrajla uyuşmuyor.")
        else:
            amount = (Decimal(row["quantity"]) * Decimal(price.unit_price)).quantize(CENT, rounding=ROUND_HALF_UP)
            row.update(unit_price=price.unit_price, price_source=price.source,
                       price_date=price.source_date.isoformat(), amount=str(amount), reason="Kullanıcı fiyatıyla hesaplandı")
            included += 1
            total += amount
    result = {"schema": "arkemx.reviewed_pilot_cost.v1", "import_id": batch.id,
              "source_sha256": batch.sha256, "filename": batch.original_filename,
              "currency": "TRY", "total": str(total), "row_count": len(rows),
              "priced_count": included, "excluded_count": len(rows) - included,
              "coverage": "complete" if included == len(rows) else "partial",
              "engineering_approved": False, "official_prices_verified": False,
              "calculation_basis": "Her satırın miktarı birim fiyatıyla çarpılır ve kuruşa yuvarlanır. Toplam, bu satır tutarlarının toplamıdır. KDV, kâr ve genel gider ayrıca eklenmez.",
              "rows": rows}
    return {**result, "preview_sha256": digest(result)}


@router.post("/preview")
def preview(project_id: str, payload: Calculation, response: Response,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    return calculate(db, user, project_id, payload)


def snapshot_view(entry):
    payload = json.loads(entry.payload_json)
    if digest(payload) != entry.snapshot_sha256:
        raise HTTPException(409, "Kayıtlı rapor bütünlüğü doğrulanamadı.")
    return {**payload, "id": entry.id, "snapshot_sha256": entry.snapshot_sha256,
            "created_at": entry.created_at}


@router.post("/snapshots", status_code=201)
def save(project_id: str, payload: Save, response: Response,
         user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    response.headers.update(NO_STORE)
    request_hash = digest({**payload.model_dump(mode="json"), "user_id": user.id})
    existing = db.scalar(select(PilotCostSnapshot).where(
        PilotCostSnapshot.project_id == project_id, PilotCostSnapshot.request_key == str(payload.request_key)))
    if existing:
        if existing.request_sha256 != request_hash:
            raise HTTPException(409, "İstek anahtarı farklı bir rapor için kullanılmış.")
        response.status_code = 200
        return snapshot_view(existing)
    result = calculate(db, user, project_id, payload)
    if result["preview_sha256"] != payload.expected_preview_sha256:
        raise HTTPException(409, "Metraj veya fiyat değişti; hesabı yeniden önizleyin.")
    if not result["priced_count"] or len(payload.title.strip()) < 3:
        raise HTTPException(422, "Başlık ve en az bir hesaplanabilir kalem gerekli.")
    frozen = {**result, "title": payload.title.strip(), "reviewed_by_id": user.id,
              "review_kind": "user_review_only"}
    entry = PilotCostSnapshot(organization_id=user.organization_id, project_id=project_id,
        import_id=str(payload.import_id), created_by_id=user.id, request_key=str(payload.request_key),
        request_sha256=request_hash, snapshot_sha256=digest(frozen),
        payload_json=json.dumps(frozen, ensure_ascii=False))
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Eşzamanlı kayıt; rapor listesini yenileyin.") from None
    return snapshot_view(entry)


@router.get("/snapshots")
def history(project_id: str, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant_project(db, user, project_id)
    entries = db.scalars(select(PilotCostSnapshot).where(
        PilotCostSnapshot.project_id == project_id, PilotCostSnapshot.organization_id == user.organization_id)
        .order_by(PilotCostSnapshot.created_at.desc(), PilotCostSnapshot.id.desc()).limit(50)).all()
    response.headers.update(NO_STORE)
    return [{k: doc[k] for k in ("id", "title", "total", "coverage", "created_at")}
            for doc in map(snapshot_view, entries)]


def owned(db, user, project_id, snapshot_id):
    tenant_project(db, user, project_id)
    entry = db.scalar(select(PilotCostSnapshot).where(
        PilotCostSnapshot.id == snapshot_id, PilotCostSnapshot.project_id == project_id,
        PilotCostSnapshot.organization_id == user.organization_id))
    if not entry:
        raise HTTPException(404, "Rapor bulunamadı.")
    return snapshot_view(entry)


@router.get("/snapshots/{snapshot_id}")
def detail(project_id: str, snapshot_id: str, response: Response,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    return owned(db, user, project_id, snapshot_id)


@router.get("/snapshots/{snapshot_id}/csv")
def download(project_id: str, snapshot_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, user, project_id, snapshot_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["ARKEMX KULLANICI KONTROLLÜ PİLOT", _csv_safe(doc["title"])])
    writer.writerow(["Kapsam", "Tüm satırlar fiyatlı" if doc["coverage"] == "complete" else "KISMİ; eksik kalemler toplam dışı"])
    writer.writerow(["Mühendis onayı / resmî kaynak doğrulaması", "Yok"])
    writer.writerow(["Hesap esası", doc["calculation_basis"]])
    writer.writerow(["Excel SHA-256", doc["source_sha256"]])
    writer.writerow(["Rapor SHA-256", doc["snapshot_sha256"]])
    writer.writerow(["Satır", "İmalat", "Miktar", "Birim", "Birim fiyat", "Tutar TRY", "Fiyat kaynağı", "Fiyat tarihi", "Durum"])
    for row in doc["rows"]:
        writer.writerow([_csv_safe(row.get(k)) for k in (
            "source_row", "description", "quantity", "unit", "unit_price", "amount", "price_source", "price_date", "reason")])
    writer.writerow(["TOPLAM" if doc["coverage"] == "complete" else "KISMİ ARA TOPLAM", doc["total"], "TRY"])
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={**NO_STORE, "Content-Disposition": f'attachment; filename="arkemx-pilot-{UUID(snapshot_id)}.csv"'})
