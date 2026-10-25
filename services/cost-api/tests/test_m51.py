"""M5.1 comparison and non-persistent revision regression tests."""
from decimal import Decimal
from types import SimpleNamespace
from sqlalchemy import select
from app.database import get_db
from app.models import CostEstimateLine
from test_m5 import setup, approve, price_payload
from test_m41 import auth
from app.m51 import _kind


def save(client, head, pid, run, cand, *, price, key, source=None):
    payload = price_payload(run, cand["candidate_id"], key=key, price=price)
    if source:
        payload["lines"][0]["price_source"] = source
    res = client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=payload)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_compare_saved_drafts_and_simulation_readonly(client, monkeypatch):
    head, pid, _, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    old = save(client, head, pid, run, cand, price="1250", key="compare-baseline-0001")
    new = save(client, head, pid, run, cand, price="1400", key="compare-target-00001")
    query = {"baseline_id": old, "target_id": new}
    res = client.get(f"/api/projects/{pid}/m51/compare", headers=head, params=query)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["baseline_total"] == "15625.00"
    assert data["target_total"] == "17500.00"
    assert data["difference"] == "1875.00"
    assert data["breakdown"]["quantity_effect"] == "0.00"
    assert data["breakdown"]["price_effect"] == "1875.00"
    assert data["counts"] == {"price_only": 1}
    assert len(data["rows"]) == 1
    assert data["rows"][0]["baseline_position"] == "DEMO-C25"
    assert data["rows"][0]["source_row"] >= 2

    scenario = client.post(f"/api/projects/{pid}/m51/simulate", headers=head, json={
        "estimate_id": old,
        "changes": [{"candidate_id": cand["candidate_id"],
                     "quantity": "13.0000", "unit_price": "1400"}]
    })
    assert scenario.status_code == 200, scenario.text
    projection = scenario.json()
    assert projection["persisted"] is False
    assert projection["status"] == "simulation_only"
    assert projection["baseline_total"] == "15625.00"
    assert projection["simulated_total"] == "18200.00"
    assert projection["difference"] == "2575.00"
    assert projection["rows"][0]["quantity_effect"] == "625.00"
    assert projection["rows"][0]["price_effect"] == "1950.00"
    assert projection["rows"][0]["rounding_adjustment"] == "0.00"
    assert client.get(f"/api/projects/{pid}/m5/estimates/{old}", headers=head).json()["lines"][0]["quantity"] == "12.5000"
    assert len(client.get(f"/api/projects/{pid}/m5/estimates", headers=head).json()) == 2


def test_m51_identical_and_source_changed_drafts(client, monkeypatch):
    head, pid, _, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    a = save(client, head, pid, run, cand, price="1250", key="compare-identical0001")
    b = save(client, head, pid, run, cand, price="1250.0000", key="compare-identical0002")
    q = {"baseline_id": a, "target_id": b}
    response = client.get(f"/api/projects/{pid}/m51/compare", params=q, headers=head)
    assert response.status_code == 200, response.text
    assert response.json()["difference"] == "0.00"
    assert response.json()["counts"]["unchanged"] == 1
    c = save(client, head, pid, run, cand, price="1250",
             key="compare-source000003", source="Alternative internal synthetic price provenance")
    q["target_id"] = c
    response = client.get(f"/api/projects/{pid}/m51/compare", params=q, headers=head)
    assert response.status_code == 200
    assert response.json()["counts"]["source_changed"] == 1


def test_m51_invalid_scenario_and_tenant_isolation(client, monkeypatch):
    head, pid, _, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    a = save(client, head, pid, run, cand, price="1250", key="m51-validation-001")
    b = save(client, head, pid, run, cand, price="1500", key="m51-validation-002")
    comp = f"/api/projects/{pid}/m51/compare"
    assert client.get(comp, headers=head, params={"baseline_id": a, "target_id": a}).status_code == 422
    outsider = auth(client, "M51 Separate Office", "m51outsider@example.com")
    assert client.get(comp, headers=outsider, params={"baseline_id": a, "target_id": b}).status_code == 404
    change = {"candidate_id": cand["candidate_id"], "quantity": "14"}
    invalid = [
      {"estimate_id": a, "changes": [{"candidate_id": cand["candidate_id"], "quantity": "0"}]},
      {"estimate_id": a, "changes": [{"candidate_id": cand["candidate_id"], "unit_price": "-3"}]},
      {"estimate_id": a, "changes": [{"candidate_id": cand["candidate_id"], "quantity": "3,4"}]},
      {"estimate_id": a, "changes": [{"candidate_id": cand["candidate_id"]}]},
      {"estimate_id": a, "changes": [change, change]},
    ]
    for body in invalid:
        assert client.post(f"/api/projects/{pid}/m51/simulate", headers=head,
                           json=body).status_code == 422
    assert client.post(f"/api/projects/{pid}/m51/simulate", headers=outsider,
                       json={"estimate_id": a, "changes": [change]}).status_code == 404
    missing = {"estimate_id": a,
               "changes": [{"candidate_id": "00000000-0000-0000-0000-000000000000", "quantity": "1"}]}
    assert client.post(f"/api/projects/{pid}/m51/simulate", headers=head,
                       json=missing).status_code == 404


def test_m51_tampered_draft_cannot_be_compared_or_simulated(client, monkeypatch):
    head, pid, _, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    a = save(client, head, pid, run, cand, price="1250", key="m51-tamper-0001")
    b = save(client, head, pid, run, cand, price="1400", key="m51-tamper-0002")
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    line = db.scalar(select(CostEstimateLine).where(CostEstimateLine.estimate_id == a))
    line.price_source = "Tampered price source without re-signing the snapshot"
    db.commit()
    gen.close()
    assert client.get(f"/api/projects/{pid}/m51/compare", headers=head,
                      params={"baseline_id": a, "target_id": b}).status_code == 409
    assert client.post(f"/api/projects/{pid}/m51/simulate", headers=head, json={
        "estimate_id": a, "changes": [{"candidate_id": cand["candidate_id"], "quantity": "15"}]
    }).status_code == 409


def test_scope_change_and_added_removed_not_misclassified_as_price():
    def r(**kwargs):
        return SimpleNamespace(**kwargs)
    old = r(unit="m3", position_code="DEMO-C25",
            quantity=Decimal("12.5"), unit_price=Decimal("1250"), price_source="test")
    new = r(unit="m3", position_code="DEMO-C30",
            quantity=Decimal("12.5"), unit_price=Decimal("1400"), price_source="test")
    assert _kind(old, new) == "scope_changed"
    assert _kind(None, new) == "added"
    assert _kind(old, None) == "removed"
    newer = r(unit="m3", position_code="DEMO-C25",
              quantity=Decimal("13"), unit_price=Decimal("1400"), price_source="test")
    assert _kind(old, newer) == "quantity_and_price"
