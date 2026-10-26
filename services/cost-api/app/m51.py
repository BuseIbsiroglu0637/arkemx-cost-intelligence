"""M5.1: immutable draft-to-draft analysis + non-persistent what-if pricing.

No catalog price ingestion; every source is an already verified M5 manual-price
snapshot. Existing M1/M2.1 metraj and M4 engineer decisions are never mutated.
"""
from decimal import Decimal
from hashlib import sha256
from collections import Counter
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .security import current_user
from .models import (User, CostEstimateLine, CostEstimate, ImportBatch,
                     CatalogVersion, CatalogPosition, WorkItem, MatchCandidate,
                     TechnicalEvidence)
from .m5 import get_estimate, _money
from .m42 import _proof
from .excel import normalized

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




def _cross_key(line):
    """Never infer continuity from row number or code alone."""
    return (line.position_id, line.position_code, normalized(line.description),
            line.unit)


def _load_many(db: Session, model, ids, key="id"):
    """Batch read; SQLite builds with a 999-bind limit remain supported."""
    ids = list(set(value for value in ids if value))
    found = {}
    column = getattr(model, key)
    for start in range(0, len(ids), 400):
        records = db.scalars(select(model).where(column.in_(ids[start:start + 400]))).all()
        for record in records:
            uid = getattr(record, key)
            if uid in found:
                raise HTTPException(409, "Duplicate historical source evidence detected")
            found[uid] = record
    return found


def _preload_lineage(db: Session, old_estimate, new_estimate, pair_rows):
    """Load 500-line history in bounded queries rather than one SELECT per line.

    The cache lives only in this comparison call and is never persisted.
    Every technical SHA and source reference is still checked independently.
    """
    lines = [line for a, b in pair_rows for line in (a, b)]
    return {
        "imports": _load_many(db, ImportBatch,
                              (old_estimate.import_id, new_estimate.import_id)),
        "versions": _load_many(db, CatalogVersion,
                               (old_estimate.version_id, new_estimate.version_id)),
        "positions": _load_many(db, CatalogPosition, (x.position_id for x in lines)),
        "items": _load_many(db, WorkItem, (x.work_item_id for x in lines)),
        "candidates": _load_many(db, MatchCandidate, (x.candidate_id for x in lines)),
        "evidence": _load_many(db, TechnicalEvidence,
                               (x.candidate_id for x in lines), "candidate_id")
    }


def _technical_scope(db: Session, line, estimate: CostEstimate, preload=None):
    """Verify both historical evidence objects, not merely their SHA labels.

    Imported Excel SHA, catalog identity and candidate lineage must agree.
    M4.1/M4.3 evidence hashes legitimately differ across imports due to source
    references; only equivalent verified technical facts may justify matching.
    """
    if not line.position_id or not line.candidate_id:
        return None
    if preload is None:
        imported = db.get(ImportBatch, estimate.import_id)
        version = db.get(CatalogVersion, estimate.version_id)
        position = db.get(CatalogPosition, line.position_id)
        item = db.get(WorkItem, line.work_item_id)
        candidate = db.get(MatchCandidate, line.candidate_id)
        evidence = db.scalar(select(TechnicalEvidence).where(
            TechnicalEvidence.candidate_id == line.candidate_id))
    else:
        imported = preload["imports"].get(estimate.import_id)
        version = preload["versions"].get(estimate.version_id)
        position = preload["positions"].get(line.position_id)
        item = preload["items"].get(line.work_item_id)
        candidate = preload["candidates"].get(line.candidate_id)
        evidence = preload["evidence"].get(line.candidate_id)
    if (not imported or imported.project_id != estimate.project_id or
            imported.sha256 != estimate.source_file_sha256 or
            not version or version.sha256 != estimate.catalog_sha256 or
            not position or position.version_id != estimate.version_id or
            position.code != line.position_code or position.unit != line.unit or
            not item or item.import_id != estimate.import_id or
            not candidate or candidate.run_id != estimate.run_id or
            candidate.work_item_id != line.work_item_id or
            candidate.position_id != line.position_id or not evidence):
        return None
    if evidence.evidence_sha256 != line.evidence_sha256:
        raise HTTPException(409, "Historical technical evidence SHA differs from cost snapshot")
    proof = _proof(evidence)  # Fails closed with HTTP409 on evidence corruption
    if not proof or proof.get("status") != "compatible" or not proof.get("approval_allowed"):
        return None
    sources = proof.get("sources")
    refs = proof.get("source_refs")
    if (not isinstance(sources, dict) or not isinstance(refs, dict) or
            not isinstance(sources.get("metraj"), dict) or
            not isinstance(sources.get("catalog"), dict) or
            sources["metraj"].get("normalized_text") != normalized(line.description) or
            sources["catalog"].get("normalized_text") != normalized(position.description) or
            sources["catalog"].get("sha256") != sha256(position.description.encode("utf-8")).hexdigest() or
            not isinstance(refs.get("metraj"), dict) or
            refs["metraj"].get("import_id") != estimate.import_id or
            refs["metraj"].get("import_sha256") != estimate.source_file_sha256 or
            refs["metraj"].get("work_item_id") != line.work_item_id or
            refs["metraj"].get("source_row") != line.source_row or
            not isinstance(refs.get("catalog"), dict) or
            refs["catalog"].get("position_id") != line.position_id or
            refs["catalog"].get("version_id") != estimate.version_id or
            refs["catalog"].get("position_code") != line.position_code or
            refs["catalog"].get("version_sha256") != estimate.catalog_sha256):
        return None
    checks = proof.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    claim = []
    seen = set()
    for c in checks:
        if not isinstance(c, dict) or c.get("key") in seen:
            return None
        key = c.get("key")
        seen.add(key)
        if not isinstance(c.get("metraj"), dict) or not isinstance(c.get("catalog"), dict):
            return None
        claim.append((key, c.get("status"), c["metraj"].get("value"),
                      c["catalog"].get("value")))
    return (proof.get("schema"), proof.get("basic_rule_version"),
            sources["catalog"].get("sha256"), tuple(sorted(claim)))


def _cross_pairs(db: Session, baseline_estimate, target_estimate,
                 old_rows, new_rows, old_map, new_map):
    """Pair ONLY one-to-one unmatched lines with verified identical scope.

    A duplicate in either *complete* draft makes this identity ambiguous even
    if one duplicate is already paired via an unchanged work_item_id.
    """
    matched = {}
    warnings = set()
    if (baseline_estimate.version_id != target_estimate.version_id or
            baseline_estimate.catalog_sha256 != target_estimate.catalog_sha256):
        return matched, warnings
    old_count = Counter(_cross_key(row) for row in old_rows)
    new_count = Counter(_cross_key(row) for row in new_rows)
    old_candidates = {}
    new_candidates = {}
    for row in old_rows:
        if row.work_item_id not in new_map:
            old_candidates[_cross_key(row)] = row
    for row in new_rows:
        if row.work_item_id not in old_map:
            new_candidates[_cross_key(row)] = row
    possible = []
    for key in old_candidates.keys() & new_candidates.keys():
        a, b = old_candidates[key], new_candidates[key]
        if old_count[key] != 1 or new_count[key] != 1:
            warnings.add(key)
            continue
        possible.append((key, a, b))
    preload = (_preload_lineage(db, baseline_estimate, target_estimate,
                               [(a, b) for _, a, b in possible])
               if db is not None and possible else None)
    for key, a, b in possible:
        left = _technical_scope(db, a, baseline_estimate, preload)
        right = _technical_scope(db, b, target_estimate, preload)
        if left is None or right is None or left != right:
            warnings.add(key)
            continue
        matched[a.work_item_id] = b.work_item_id
    return matched, warnings


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

    # Stable work_item_id remains authoritative inside one import.
    # Cross-import pairs are additionally accepted ONLY for unique, verified
    # catalog-position / description / unit / equivalent technical proof.
    old_map = {row.work_item_id: row for row in old_rows}
    new_map = {row.work_item_id: row for row in new_rows}
    if len(old_map) != len(old_rows) or len(new_map) != len(new_rows):
        raise HTTPException(409, "Ayni taslakta yinelenen is kalemi")
    old_estimate = db.get(CostEstimate, baseline_id)
    new_estimate = db.get(CostEstimate, target_id)
    pairs, unresolved = _cross_pairs(db, old_estimate, new_estimate,
                                     old_rows, new_rows, old_map, new_map)
    joined = []
    consumed = set()
    for old in old_rows:
        new = new_map.get(old.work_item_id)
        cross_import = False
        if new is None and old.work_item_id in pairs:
            new = new_map[pairs[old.work_item_id]]
            cross_import = True
        if new:
            consumed.add(new.work_item_id)
        joined.append((old, new, cross_import))
    for new in new_rows:
        if new.work_item_id not in consumed:
            joined.append((None, new, False))
    joined.sort(key=lambda pair: (
        (pair[1] or pair[0]).source_row,
        (pair[1] or pair[0]).work_item_id))
    if len(joined) > MAX_COMPARE_ROWS:
        raise HTTPException(409, "Pilot karsilastirma siniri asildi")
    totals = {"quantity_effect": ZERO, "price_effect": ZERO,
              "rounding_adjustment": ZERO, "unattributed_effect": ZERO}
    counter = {}
    results = []
    for old, new, cross_import in joined:
        key = (new or old).work_item_id
        if cross_import:
            # Difference in full evidence SHA alone is not scope change:
            # technical facts were independently verified as equivalent.
            if old.quantity != new.quantity and old.unit_price != new.unit_price:
                kind = "quantity_and_price"
            elif old.quantity != new.quantity:
                kind = "quantity_only"
            elif old.unit_price != new.unit_price:
                kind = "price_only"
            elif old.price_source != new.price_source:
                kind = "source_changed"
            else:
                kind = "unchanged"
        else:
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
            "baseline_work_item_id": old.work_item_id if old else None,
            "target_work_item_id": new.work_item_id if new else None,
            "matching_basis": ("verified_cross_import" if cross_import else
                               "original_work_item" if old and new else
                               "unmatched_requires_review" if
                               _cross_key(old or new) in unresolved else "unmatched"),
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
        "verified_cross_import_pairs": len(pairs),
        "ambiguous_identity_groups": len(unresolved),
        "total_rows": len(results), "page": page, "page_size": page_size,
        "rows": results[start:start + page_size],
        "note": "Yalniz benzersiz, ayni katalog poz kimligine, aciklama/birim ve dogrulanmis teknik kapsama sahip iki farkli Excel satiri birlikte ele alinir. Tekrar ve belirsizliklerde otomatik esleme yapilmaz. Miktar etkisi eski fiyatla, fiyat etkisi yeni miktarla hesaplanir. Degisen kapsam ve eslesmeyen kalemlerin etkisi ayrica gosterilir. Bu islem yalnizca sentetik taslak karsilastirmasidir."
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
