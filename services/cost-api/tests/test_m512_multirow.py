"""M5.1.2 scale/safety regression: 100/500 distinct revised positions.

These synthetic tests exercise the pairing engine and bounded DB reads.
They do NOT claim a 500-row full M1->M4->M5 production acceptance.
"""
from decimal import Decimal
from types import SimpleNamespace
import pytest
from sqlalchemy import Column, String, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

import app.m51 as m51


def line(i, rev, *, code=None, description=None, unit="m³"):
    return SimpleNamespace(
        work_item_id=f"{rev}-{i:04d}",
        position_id=f"position-{i:04d}",
        position_code=code or f"DEMO-{i:04d}",
        description=description or f"Ornek imalat tipi {i:04d} kapsam sabit",
        source_row=i+2,
        unit=unit,
        quantity=Decimal("12.5000") if rev == "before" else Decimal("13.0000"),
        unit_price=Decimal("1250.0000"),
        price_source="Sentetik fiyat kaynagi",
    )


def estimate():
    return SimpleNamespace(version_id="catalog-version-1",
                           catalog_sha256="c"*64)


@pytest.mark.parametrize("count", [100, 500])
def test_m512_cross_import_many_unique_rows_pair_and_decompose(monkeypatch,count):
    old = [line(i, "before") for i in range(count)]
    new = [line(i, "after") for i in reversed(range(count))]
    preload_calls = []
    monkeypatch.setattr(m51, "_preload_lineage",
        lambda db, a, b, pairs: preload_calls.append(len(pairs)) or {})
    monkeypatch.setattr(m51, "_technical_scope",
        lambda db, row, est, preload=None: ("verified-catalog","same-scope",row.position_id))
    left = {x.work_item_id:x for x in old}
    right = {x.work_item_id:x for x in new}
    pairs, unresolved = m51._cross_pairs(object(),estimate(),estimate(),
                                         old,new,left,right)
    assert len(pairs) == count
    assert not unresolved
    assert preload_calls == [count]
    for i in range(count):
        assert pairs[f"before-{i:04d}"] == f"after-{i:04d}"
    totals = {"quantity_effect": Decimal("0.00"),
              "price_effect":Decimal("0.00"),
              "rounding_adjustment":Decimal("0.00")}
    for i in range(count):
        a=old[i];b=right[pairs[a.work_item_id]]
        old_total=m51._money(a.quantity*a.unit_price)
        new_total=m51._money(b.quantity*b.unit_price)
        effects=m51._effects(a.quantity,a.unit_price,b.quantity,b.unit_price,
                             old_total,new_total)
        for key in totals:totals[key]+=effects[key]
    assert totals["quantity_effect"] == Decimal(625*count)
    assert totals["price_effect"] == Decimal("0.00")
    assert totals["rounding_adjustment"] == Decimal("0.00")


def test_m512_duplicates_and_scope_changes_remain_unmatched(monkeypatch):
    monkeypatch.setattr(m51, "_technical_scope",
        lambda db, row, est, preload=None: ("compatible",row.position_id))
    old=[line(i,"before") for i in range(100)]
    new=[line(i,"after") for i in range(100)]
    # Same poz appears twice in one draft: not a unique 1-to-1 identity.
    old.append(line(5,"duplicate"))
    # Scope change: identical poz code but differing imalat title.
    new[6].description="Ornek imalat tipi 0006 nakliye haric"
    # Different position/description cannot be inferred from matching row number.
    new[7].position_id="different-position-7"
    # Different unit must never contribute to a quantity-only effect.
    new[8].unit="m²"
    # Different code with same position also fails closed.
    new[9].position_code="OTHER"
    left={x.work_item_id:x for x in old}
    right={x.work_item_id:x for x in new}
    pairs,warnings=m51._cross_pairs(None,estimate(),estimate(),
                                    old,new,left,right)
    assert len(pairs)==95
    for k in [5,6,7,8,9]: assert f"before-{k:04d}" not in pairs
    assert len(warnings)==1  # duplicate identity diagnosed explicitly


def test_m512_changed_evidence_never_auto_pairs(monkeypatch):
    monkeypatch.setattr(m51,"_technical_scope",
        lambda db, row, est, preload=None: (row.position_id,row.work_item_id[0]))
    a,b=line(1,"before"),line(1,"after")
    pairs,warnings=m51._cross_pairs(None,estimate(),estimate(),
        [a],[b],{a.work_item_id:a},{b.work_item_id:b})
    assert not pairs and len(warnings)==1


def test_m512_batched_database_reads_no_large_sqlite_in_expression():
    Base=declarative_base()
    class Entry(Base):
        __tablename__="m512_fixture_entries"
        id=Column(String(36),primary_key=True)
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    with Session() as db:
        db.add_all(Entry(id=f"id-{i:04d}") for i in range(1200))
        db.commit()
        statements=[]
        def capture(conn,cursor,statement,params,context,executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append((statement,len(params)))
        event.listen(engine,"before_cursor_execute",capture)
        try:
            found=m51._load_many(db,Entry,
                  (f"id-{i:04d}" for i in range(1200)))
        finally:
            event.remove(engine,"before_cursor_execute",capture)
        assert len(found)==1200
        assert len(statements)==3
        assert all(bind_count<=400 for _,bind_count in statements)
    engine.dispose()
