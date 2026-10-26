"""M5.1.1: immutable cross-import line linkage with strict review fallback."""
from types import SimpleNamespace
from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy import select
from app.database import get_db
from app.models import CostEstimateLine, CostEstimate, TechnicalEvidence
from app.m51 import _cross_pairs, _cross_key
from test_m5 import setup, approve, price_payload
from test_m43 import enqueue, step
from test_m41 import auth


def revision_excel(description="Hazır beton döküm C25/30 nakliye dahildir",
                   quantity=13, unit="m3"):
    w = Workbook()
    sheet = w.active
    sheet.append(["İmalat Açıklaması", "Miktar", "Birim"])
    sheet.append([description, quantity, unit])
    out = BytesIO()
    w.save(out)
    return out.getvalue()


def pair_of_drafts(client, monkeypatch, *, new_description=None, new_unit="m3",
                   new_price="1250"):
    head, pid, catalog, old_run, old_cand = setup(client, monkeypatch)
    approve(client, head, pid, old_run, old_cand)
    old_req = price_payload(old_run, old_cand["candidate_id"],
                            key="m511-original-priced", price="1250")
    old = client.post(f"/api/projects/{pid}/m5/estimates",
                      headers=head, json=old_req)
    assert old.status_code == 201, old.text

    revision = revision_excel(description=new_description or
        "Hazır beton döküm C25/30 nakliye dahildir", unit=new_unit)
    uploaded = client.post(f"/api/projects/{pid}/imports", headers=head,
        files={"file": ("r02.xlsx", revision)})
    assert uploaded.status_code == 201, uploaded.text
    # M4.3 and M4.2 must be redone; never transfer approvals automatically.
    assert client.get(f"/api/projects/{pid}/m5/eligible",headers=head).status_code==409
    job = enqueue(client, head, pid, catalog)
    assert job.status_code == 202, job.text
    assert step(client, job.json()["id"])
    assert client.get(f"/api/projects/{pid}/m43/jobs/{job.json()['id']}",
                      headers=head).json()["status"] == "completed"
    q = client.get(f"/api/projects/{pid}/m42/queue",headers=head,
        params={"status":"compatible"})
    assert q.status_code == 200, q.text
    eligible = q.json()["rows"]
    if eligible:
        candidate = eligible[0]
        approve(client, head, pid, job.json()["run_id"], candidate)
        new_req = price_payload(job.json()["run_id"], candidate["candidate_id"],
                                key="m511-revised-priced", price=new_price)
        new = client.post(f"/api/projects/{pid}/m5/estimates",
                          headers=head, json=new_req)
        assert new.status_code == 201, new.text
        return head, pid, old.json()["id"], new.json()["id"]
    return head, pid, old.json()["id"], None


def compare(client, head, pid, old, new):
    return client.get(f"/api/projects/{pid}/m51/compare",headers=head,
        params={"baseline_id":old,"target_id":new})


def test_m511_full_r02_1250_quantity_attribution_from_distinct_excels(client,monkeypatch):
    head, pid, old, new = pair_of_drafts(client,monkeypatch)
    response = compare(client,head,pid,old,new)
    assert response.status_code == 200,response.text
    body = response.json()
    assert body["baseline_total"]=="15625.00"
    assert body["target_total"]=="16250.00"
    assert body["difference"]=="625.00"
    assert body["breakdown"]=={
        "quantity_effect":"625.00",
        "price_effect":"0.00",
        "rounding_adjustment":"0.00",
        "unattributed_effect":"0.00"}
    assert body["counts"]=={"quantity_only":1}
    assert body["verified_cross_import_pairs"]==1
    assert body["ambiguous_identity_groups"]==0
    assert body["total_rows"]==1
    row=body["rows"][0]
    assert row["matching_basis"]=="verified_cross_import"
    assert row["baseline_work_item_id"]!=row["target_work_item_id"]
    assert row["baseline_quantity"]=="12.5000" and row["target_quantity"]=="13.0000"
    assert row["baseline_unit"]==row["target_unit"]=="m³"
    assert row["baseline_position"]==row["target_position"]=="DEMO-C25"
    assert row["quantity_effect"]=="625.00" and row["unattributed_effect"]=="0.00"
    # Both drafts stay intact, with the same historical hash and amounts.
    a=client.get(f"/api/projects/{pid}/m5/estimates/{old}",headers=head).json()
    b=client.get(f"/api/projects/{pid}/m5/estimates/{new}",headers=head).json()
    assert a["total"]=="15625.00" and b["total"]=="16250.00"
    assert a["snapshot_sha256"] and b["snapshot_sha256"]


def test_m511_both_quantity_and_price_effects_cross_excel(client,monkeypatch):
    head,pid,old,new=pair_of_drafts(client,monkeypatch,new_price="1400")
    body=compare(client,head,pid,old,new).json()
    assert body["difference"]=="2575.00"
    assert body["breakdown"]["quantity_effect"]=="625.00"
    assert body["breakdown"]["price_effect"]=="1950.00"
    assert body["breakdown"]["unattributed_effect"]=="0.00"
    assert body["counts"]=={"quantity_and_price":1}


def test_m511_changed_scope_never_auto_pairs(client,monkeypatch):
    head,pid,old,new=pair_of_drafts(client,monkeypatch,
        new_description="Hazır beton döküm C25/30 nakliye dahildir ek kalıp hizmeti")
    if new is None:
        return # M4.3 correctly rejected this new technical scope
    body=compare(client,head,pid,old,new).json()
    assert body["verified_cross_import_pairs"]==0
    assert body["breakdown"]["quantity_effect"]=="0.00"
    assert body["counts"]=={"removed":1,"added":1}


def test_m511_tampered_technical_evidence_is_not_accepted_as_lineage(client,monkeypatch):
    head,pid,old,new=pair_of_drafts(client,monkeypatch)
    g=client.app.dependency_overrides[get_db]();db=next(g)
    line=db.scalar(select(CostEstimateLine).where(CostEstimateLine.estimate_id==new))
    evidence=db.scalar(select(TechnicalEvidence).where(
        TechnicalEvidence.candidate_id==line.candidate_id))
    evidence.evidence_sha256="0"*64
    db.commit();g.close()
    result=compare(client,head,pid,old,new)
    assert result.status_code==409,result.text
    assert client.get(f"/api/projects/{pid}/m5/estimates/{old}",headers=head).status_code==200


def _mock(id, position="p1", code="C25", desc="Hazır beton C25/30 nakliye dahildir",
          unit="m³"):
    return SimpleNamespace(work_item_id=id,position_id=position,position_code=code,
        description=desc,unit=unit,quantity=Decimal("12.5"),
        unit_price=Decimal("1250"),price_source="synthetic")


def test_m511_ambiguous_duplicate_codes_do_not_auto_pair(monkeypatch):
    import app.m51 as module
    monkeypatch.setattr(module,"_technical_scope",lambda db,line,estimate,preload=None:("verified",))
    e=SimpleNamespace(version_id="v1",catalog_sha256="same")
    a,b,c=_mock("old-a"),_mock("old-b"),_mock("new-c")
    old=[a,b];new=[c]
    pairs,unresolved=_cross_pairs(None,e,e,old,new,
        {x.work_item_id:x for x in old},{x.work_item_id:x for x in new})
    assert not pairs and len(unresolved)==1


def test_m511_changed_catalog_or_poz_disallows_cross_pair(monkeypatch):
    import app.m51 as module
    monkeypatch.setattr(module,"_technical_scope",lambda db,line,estimate:("verified",))
    a,b=_mock("old"),_mock("new")
    e1=SimpleNamespace(version_id="v1",catalog_sha256="old")
    e2=SimpleNamespace(version_id="v2",catalog_sha256="new")
    assert _cross_pairs(None,e1,e2,[a],[b],{a.work_item_id:a},{b.work_item_id:b})[0]=={}
    b.position_id="DIFFERENT"
    assert _cross_pairs(None,e1,e1,[a],[b],{a.work_item_id:a},{b.work_item_id:b})[0]=={}


def test_m511_cross_import_is_readonly_and_tenant_isolated(client,monkeypatch):
    head,pid,old,new=pair_of_drafts(client,monkeypatch)
    outsider=auth(client,"Other M511 Office","m511outsider@example.com")
    assert compare(client,outsider,pid,old,new).status_code==404
    before=client.get(f"/api/projects/{pid}/m5/estimates",headers=head).json()
    assert compare(client,head,pid,old,new).status_code==200
    after=client.get(f"/api/projects/{pid}/m5/estimates",headers=head).json()
    assert before==after
