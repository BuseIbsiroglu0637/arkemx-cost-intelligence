"""M5.1: immutable draft-to-draft analysis + non-persistent what-if pricing.

No catalog price ingestion; every source is an already verified M5 manual-price
snapshot. Existing M1/M2.1 metraj and M4 engineer decisions are never mutated.
"""
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .security import current_user
from .models import User, CostEstimateLine
from .m5 import get_estimate, _money

router = APIRouter(prefix="/api/projects/{project_id}/m51", tags=["M5.1 Cost Analysis"])
ZERO = Decimal("0.00")
MAX_COMPARE_ROWS = 1000
MAX_SCENARIO_LINES = 500
DECIMAL_RE = r"^[0-9]{1,9}(\.[0-9]{1,4})?$"


class ScenarioChange(BaseModel):
    candidate_id: str = Field(min_length=36, max_length=36)
    quantity: str | None = Field(default=None, pattern=DECIMAL_RE)
    unit_price: str | None = Field(default=None, pattern=DECIMAL_RE)


class ScenarioRequest(BaseModel):
    estimate_id: str = Field(min_length=36, max_length=36)
    changes: list[ScenarioChange] = Field(min_length=1, max_length=MAX_SCENARIO_LINES)


def _amount(line):
    return Decimal(str(line.amount))


def _effects(q0: Decimal, p0: Decimal, q1: Decimal, p1: Decimal,
             old_amount: Decimal, new_amount: Decimal):
    # Quantity first, price second at the new quantity. Neither effect
    # includes the other twice; rounding remainder is explicitly disclosed.
    q_effect = _money((q1 - q0) * p0)
    p_effect = _money(q1 * (p1 - p0))
    difference = _money(new_amount - old_amount)
    return {
        "quantity_effect": q_effect,
        "price_effect": p_effect,
        "rounding_adjustment": difference - q_effect - p_effect,
    }


def _to_str(values):
    return {key: str(value) if isinstance(value, Decimal) else value
            for key, value in values.items()}


def _base_and_lines(project_id: str, estimate_id: str, user: User, db: Session):
    # M5 verifies tenant + exact persisted SHA (including bounded legacy
    # decimal representation compatibility), line arithmetic, and line count.
    verified = get_estimate(project_id, estimate_id, user, db)
    lines = db.scalars(select(CostEstimateLine)
        .where(CostEstimateLine.estimate_id == estimate_id)
        .order_by(CostEstimateLine.source_row, CostEstimateLine.position_code)).all()
    if len(lines) != verified["line_count"]:
        raise HTTPException(409, "Taslak kalem sayisi degisti")
    if len(lines) > MAX_SCENARIO_LINES:
        raise HTTPException(409, "Pilot taslak siniri asildi")
    return verified, lines


def _kind(old, new):
    if old is None:
        return "added"
    if new is None:
        return "removed"
    # Changed description, technical evidence, unit or poz must NOT be
    # misclassified as a pure price movement even when a row id survives.
    if (old.unit != new.unit or old.position_code != new.position_code
            or old.description != new.description
            or old.evidence_sha256 != new.evidence_sha256):
        return "scope_changed"
    quantity_changed = old.quantity != new.quantity
    price_changed = old.unit_price != new.unit_price
    if quantity_changed and price_changed:
        return "quantity_and_price"
    if quantity_changed:
        return "quantity_only"
    if price_changed:
        return "price_only"
    if old.price_source != new.price_source:
        return "source_changed"
    return "unchanged"


@router.get("/compare")
def compare_estimates(
    project_id: str,
    baseline_id: str = Query(min_length=36, max_length=36),
    target_id: str = Query(min_length=36, max_length=36),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if baseline_id == target_id:
        raise HTTPException(422, "Karsilastirma icin iki ayri taslak secin")
    baseline, old_rows = _base_and_lines(project_id, baseline_id, user, db)
    target, new_rows = _base_and_lines(project_id, target_id, user, db)
    if baseline["currency"] != "TRY" or target["currency"] != "TRY":
        raise HTTPException(409, "Karsilastirma TRY taslaklari icindir")

    # A project WorkItem is persistent across M2.1 revisions. Re-imported
    # spreadsheets have new work_item_ids; do not guess a false pairing
    # from identical titles or shared source row numbers.
    old_map = {row.work_item_id: row for row in old_rows}
    new_map = {row.work_item_id: row for row in new_rows}
    if len(old_map) != len(old_rows) or len(new_map) != len(new_rows):
        raise HTTPException(409, "Ayni taslakta yinelenen is kalemi")
    keys = sorted(set(old_map) | set(new_map),
                  key=lambda id: (
                      (new_map.get(id) or old_map[id]).source_row,
                      id))
    if len(keys) > MAX_COMPARE_ROWS:
        raise HTTPException(409, "Pilot karsilastirma siniri asildi")
    totals = {"quantity_effect": ZERO, "price_effect": ZERO,
              "rounding_adjustment": ZERO, "unattributed_effect": ZERO}
    counter = {}
    results = []
    for key in keys:
        old = old_map.get(key)
        new = new_map.get(key)
        kind = _kind(old, new)
        counter[kind] = counter.get(kind, 0) + 1
        before = _amount(old) if old else ZERO
        after = _amount(new) if new else ZERO
        difference = after - before
        effects = {"quantity_effect": ZERO, "price_effect": ZERO,
                   "rounding_adjustment": ZERO, "unattributed_effect": ZERO}
        if old is not None and new is not None and kind != "scope_changed":
            effects.update(_effects(old.quantity, old.unit_price,
                                    new.quantity, new.unit_price, before, after))
        else:
            effects["unattributed_effect"] = difference
        for name, amount in effects.items():
            totals[name] += amount
        results.append({
            "work_item_id": key, "status": kind,
            "source_row": (new or old).source_row,
            "description": (new or old).description,
            "baseline_position": old.position_code if old else None,
            "target_position": new.position_code if new else None,
            "baseline_unit": old.unit if old else None,
            "target_unit": new.unit if new else None,
            "baseline_quantity": str(old.quantity) if old else None,
            "target_quantity": str(new.quantity) if new else None,
            "baseline_unit_price": str(old.unit_price) if old else None,
            "target_unit_price": str(new.unit_price) if new else None,
            "baseline_price_source": old.price_source if old else None,
            "target_price_source": new.price_source if new else None,
            "baseline_amount": str(before), "target_amount": str(after),
            "difference": str(difference),
            **_to_str(effects),
        })
    old_total = Decimal(baseline["total"])
    new_total = Decimal(target["total"])
    change = new_total - old_total
    if (sum((Decimal(r["baseline_amount"]) for r in results), ZERO) != old_total or
            sum((Decimal(r["target_amount"]) for r in results), ZERO) != new_total or
            sum(totals.values(), ZERO) != change):
        raise HTTPException(409, "Taslak karsilastirma toplamlari tutarsiz")
    start = (page - 1) * page_size
    return {
        "status": "comparison_only", "currency": "TRY",
        "baseline": {"id": baseline_id, "title": baseline["title"],
                     "snapshot_sha256": baseline["snapshot_sha256"]},
        "target": {"id": target_id, "title": target["title"],
                   "snapshot_sha256": target["snapshot_sha256"]},
        "baseline_total": str(old_total), "target_total": str(new_total),
        "difference": str(change),
        "breakdown": _to_str(totals), "counts": counter,
        "total_rows": len(results), "page": page, "page_size": page_size,
        "rows": results[start:start + page_size],
        "note": "Miktar etkisi eski fiyatla; fiyat etkisi yeni miktarla hesaplanir. Kapsami degisen, eklenen ve cikarilan pozlar ayrica gosterilir. Ayrica yuvarlama farki olabilir. Yalnizca sentetik taslak karsilastirmasidir."
    }


@router.post("/simulate")
def simulate_revision(
    project_id: str, payload: ScenarioRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    baseline, rows = _base_and_lines(project_id, payload.estimate_id, user, db)
    if baseline["currency"] != "TRY":
        raise HTTPException(409, "Simulasyon para birimi TRY olmalidir")
    lookup = {row.candidate_id: row for row in rows}
    selected = set()
    old_total = Decimal(baseline["total"])
    total_difference = ZERO
    details = []
    for change in payload.changes:
        if change.candidate_id in selected:
            raise HTTPException(422, "Ayni poz icin tekrar eden simulasyon degisikligi")
        selected.add(change.candidate_id)
        line = lookup.get(change.candidate_id)
        if not line:
            raise HTTPException(404, "Taslakta secilen poz bulunamadi")
        if change.quantity is None and change.unit_price is None:
            raise HTTPException(422, "Miktar veya birim fiyat degisikligi gerekli")
        q1 = Decimal(change.quantity) if change.quantity is not None else line.quantity
        p1 = Decimal(change.unit_price) if change.unit_price is not None else line.unit_price
        if q1 <= 0 or p1 <= 0:
            raise HTTPException(422, "Miktar ve fiyat pozitif olmali")
        new_amount = _money(q1 * p1)
        before = line.amount
        delta = new_amount - before
        total_difference += delta
        details.append({
            "candidate_id": line.candidate_id,
            "source_row": line.source_row, "position_code": line.position_code,
            "unit": line.unit, "baseline_quantity": str(line.quantity),
            "scenario_quantity": str(q1),
            "baseline_unit_price": str(line.unit_price),
            "scenario_unit_price": str(p1),
            "baseline_amount": str(before), "scenario_amount": str(new_amount),
            "difference": str(delta),
            **_to_str(_effects(line.quantity, line.unit_price, q1, p1, before, new_amount))
        })
    return {
        "status": "simulation_only", "persisted": False,
        "baseline_id": payload.estimate_id,
        "baseline_sha256": baseline["snapshot_sha256"],
        "currency": "TRY",
        "baseline_total": str(old_total), "simulated_total": str(old_total + total_difference),
        "difference": str(total_difference), "changed_lines": len(details),
        "rows": details,
        "note": "Simulasyon gercek metraj revizyonu, muhendis onayi veya resmi fiyat guncellemesi yapmaz. Kayitli taslaklar degismez."
    }
