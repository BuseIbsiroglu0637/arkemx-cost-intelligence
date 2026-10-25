"""M5 draft pricing: approved-only, immutable snapshots and tenant/rights safety."""
from sqlalchemy import select
from app.database import get_db
from app.models import TechnicalEvidence, WorkItemRevision, User, CostEstimateLine
from app import catalog_operator
from test_m41 import auth
from test_m42 import ready


def setup(client, monkeypatch):
    head, pid, catalog, run_id = ready(client, monkeypatch)
    response = client.get(f"/api/projects/{pid}/m42/queue", headers=head,
                          params={"status": "compatible"})
    assert response.status_code == 200, response.text
    cand = response.json()["rows"][0]
    return head, pid, catalog, run_id, cand


def price_payload(run, candidate, *, key="m5-request-000001", price="123.4500"):
    return {"run_id": run, "title": "Sentetik Taslak Hesap",
            "request_key": key,
            "lines": [{"candidate_id": candidate, "unit_price": price,
                       "price_source": "Fiktif manuel deneme fiyati - resmi degil"}]}


def approve(client, head, pid, run_id, cand):
    res = client.post(f"/api/projects/{pid}/m2/decisions", headers=head,
                      json={"run_id": run_id, "candidate_id": cand["candidate_id"],
                            "action": "approve",
                            "reason": "Verified full synthetic technical compatibility"})
    assert res.status_code == 201, res.text


def test_manual_draft_and_immutable_snapshot(client, monkeypatch):
    head, pid, catalog, run, cand = setup(client, monkeypatch)
    before = client.get(f"/api/projects/{pid}/m5/eligible", headers=head)
    assert before.status_code == 200, before.text
    assert before.json()["eligible_count"] == 0
    payload = price_payload(run, cand["candidate_id"])
    assert client.post(f"/api/projects/{pid}/m5/estimates", headers=head,
                       json=payload).status_code == 409
    approve(client, head, pid, run, cand)
    eligible = client.get(f"/api/projects/{pid}/m5/eligible", headers=head)
    assert eligible.status_code == 200
    assert eligible.json()["eligible_count"] == 1
    assert eligible.json()["items"][0]["quantity"] == "12.5000"
    created = client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=payload)
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["total"] == "1543.13"
    assert draft["line_count"] == 1
    assert draft["status"] == "draft" and not draft["official_prices"]
    again = client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=payload)
    assert again.status_code == 201 and again.json()["id"] == draft["id"]
    conflicting = {**payload, "title": "Tamamen farkli taslak"}
    assert client.post(f"/api/projects/{pid}/m5/estimates", headers=head,
                       json=conflicting).status_code == 409
    doc = client.get(f"/api/projects/{pid}/m5/estimates/{draft['id']}", headers=head)
    assert doc.status_code == 200
    assert doc.json()["lines"][0]["unit_price"] == "123.4500"
    csv = client.get(f"/api/projects/{pid}/m5/estimates/{draft['id']}/csv", headers=head)
    assert csv.status_code == 200
    assert csv.content.startswith(b"\xef\xbb\xbf") and b"1543.13" in csv.content
    history = client.get(f"/api/projects/{pid}/m5/estimates", headers=head)
    assert len(history.json()) == 1

    outsider = auth(client, "Other M5 Office", "m5outsider@example.com")
    assert client.get(f"/api/projects/{pid}/m5/estimates", headers=outsider).status_code == 404
    assert client.get(f"/api/projects/{pid}/m5/estimates/{draft['id']}/csv", headers=outsider).status_code == 404
    assert client.post(f"/api/projects/{pid}/m5/estimates", headers=outsider, json=payload).status_code == 404

    # Later source rights revocation cannot rewrite historical draft.
    catalog_operator.record_review(
        catalog["id"], "Independent operator",
        b"Revoked synthetic rights after draft snapshot tests",
        "Synthetic rights revoked for M5 safety test", "revoke")
    assert client.get(f"/api/projects/{pid}/m5/eligible", headers=head).status_code == 403
    assert client.get(f"/api/projects/{pid}/m5/estimates/{draft['id']}",
                      headers=head).json()["total"] == "1543.13"


def test_stale_evidence_and_price_guards(client, monkeypatch):
    head, pid, catalog, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    payload = price_payload(run, cand["candidate_id"])
    for bad in ("0", "-1", "NaN", "12,50", "2.12345"):
        test = price_payload(run, cand["candidate_id"], price=bad)
        assert client.post(f"/api/projects/{pid}/m5/estimates", headers=head,
                           json=test).status_code == 422
    missing = price_payload(run, "00000000-0000-0000-0000-000000000000")
    assert client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=missing).status_code == 409
    duplicate = {**payload, "lines": [payload["lines"][0], payload["lines"][0]]}
    assert client.post(f"/api/projects/{pid}/m5/estimates", headers=head,
                       json=duplicate).status_code == 409
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    ev = db.scalar(select(TechnicalEvidence).where(TechnicalEvidence.candidate_id == cand["candidate_id"]))
    ev.evidence_sha256 = "0" * 64
    db.commit()
    gen.close()
    assert client.get(f"/api/projects/{pid}/m5/eligible", headers=head).status_code == 409
    assert client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=payload).status_code == 409


def test_import_change_blocks_new_cost_draft(client, monkeypatch):
    head, pid, catalog, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    # A later edit to a previously-approved metraj must close pricing as well.
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    from app.models import WorkItem
    item = db.get(WorkItem, cand["work_item_id"])
    reviewer = db.scalar(select(User).where(User.email=="m42pilot@example.com"))
    db.add(WorkItemRevision(work_item_id=item.id, revision=1,
        description="Hazir beton C30/37 nakliye dahil",
        quantity=item.quantity, unit=item.normalized_unit,
        corrected_by_id=reviewer.id, reason="M5 synthetic revision safety test"))
    db.commit()
    gen.close()
    assert client.get(f"/api/projects/{pid}/m5/eligible", headers=head).status_code == 409


def test_estimate_hash_and_amount_tampering_fail_closed(client, monkeypatch):
    head, pid, catalog, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    payload = price_payload(run, cand["candidate_id"], key="m5-tamper-check001")
    result = client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=payload)
    assert result.status_code == 201, result.text
    estimate_id = result.json()["id"]
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    line = db.scalar(select(CostEstimateLine).where(CostEstimateLine.estimate_id == estimate_id))
    line.amount = line.amount + 1
    db.commit()
    gen.close()
    assert client.get(f"/api/projects/{pid}/m5/estimates/{estimate_id}",
                      headers=head).status_code == 409
    assert client.get(f"/api/projects/{pid}/m5/estimates/{estimate_id}/csv",
                      headers=head).status_code == 409


def test_blank_price_provenance_rejected(client, monkeypatch):
    head, pid, catalog, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    payload = price_payload(run, cand["candidate_id"], key="m5-blank-source001")
    payload["lines"][0]["price_source"] = "                  "
    assert client.post(f"/api/projects/{pid}/m5/estimates",
                       headers=head, json=payload).status_code == 422
