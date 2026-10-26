"""M4.3.1: fixture identity checks on 100-line / 100-position work.

Prior immutable technical evidence must not be edited or silently trusted when
it predates the position-identity gate. All test sources are invented.
"""
from io import BytesIO
from uuid import uuid4
from openpyxl import Workbook
from sqlalchemy.orm import sessionmaker
from app import catalog_operator, evidence_v41, m43_worker
from app.catalog_operator import CONFIRM
from app.database import get_db
from app.evidence_v41 import analyze, verify_evidence
from app.identity_guard import fixture_identity, approval_identity_issue
from test_m41 import auth


def _description(i):
    return f"Sentetik test beton C25/30 kalem {i:03d} nakliye dahil"


def _prepare(client, monkeypatch, n=100):
    head = auth(client, f"M431 Fixture {uuid4()}", f"m431-{uuid4().hex}@example.com")
    project = client.post("/api/projects", headers=head,
                          json={"name": "M431-100-ID-CHECK"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    wb = Workbook(); sheet = wb.active
    sheet.append(["İmalat Açıklaması", "Miktar", "Birim"])
    for i in range(1, n+1):
        sheet.append([_description(i), 12.5, "m3"])
    out = BytesIO(); wb.save(out)
    imported = client.post(f"/api/projects/{pid}/imports", headers=head,
                           files={"file":("m431-r01.xlsx",out.getvalue())})
    assert imported.status_code == 201, imported.text
    assert imported.json()["row_count"] == n
    csv = "Poz Kodu;Poz Tanımı;Birim\n" + "".join(
        f"DEMO-M512-{i:03d};{_description(i)};m3\n" for i in range(1,n+1))
    cat = client.post("/api/m3/imports", headers=head,
       data={"institution":"OTHER","year":"2026","period":"M431-100"},
       files={"file":("m431-catalog.csv",csv.encode("utf-8-sig"))})
    assert cat.status_code == 201, cat.text
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        monkeypatch.setattr(catalog_operator, "SessionLocal", sessionmaker(bind=db.get_bind()))
    finally:
        generator.close()
    catalog_operator.record_review(
        cat.json()["id"], "Local synthetic test operator",
        b"Original M431 synthetic dataset created entirely by this test suite.",
        "Invented 100 position descriptions and matching permission for local test",
        "approve", confirmation=CONFIRM)
    return head,pid,cat.json()


def _run(client,head,pid,cat):
    req=client.post(f"/api/projects/{pid}/m43/jobs",headers=head,json={
        "version_id":cat["version_id"],"idempotency_key":str(uuid4())})
    assert req.status_code == 202, req.text
    job=req.json()["id"]
    for _ in range(5):
        generator=client.app.dependency_overrides[get_db]()
        db=next(generator)
        try:
            assert m43_worker.process_chunk(db,job,chunk_size=20)
        finally:
            generator.close()
    completed=client.get(f"/api/projects/{pid}/m43/jobs/{job}",headers=head)
    assert completed.status_code==200
    assert completed.json()["status"]=="completed"
    assert completed.json()["processed_rows"]==100
    return req.json()


def test_m431_fixture_identity_unambiguous_and_only_limited_scope():
    left=_description(1);right=_description(2)
    good=fixture_identity(left,left,"DEMO-M512-001")
    assert good["status"]=="match" and good["code"] is None
    assert good["metraj"]["value"] == "001"
    assert good["catalog"]["value"] == "001"
    for a,b,code in [
        (left,right,"DEMO-M512-002"),
        (left,left,"DEMO-M512-002"),
    ]:
        check=fixture_identity(a,b,code)
        assert check["status"]=="block"
        assert check["code"]=="M512_ITEM_ID_MISMATCH"
    assert fixture_identity(left,left,"CSB-2026-001") is None
    assert fixture_identity("Kalem 001", "Kalem 002", "DEMO-OTHER") is None
    assert fixture_identity(left,"Sentetik test beton C25/30 nakliye dahil",
                            "DEMO-M512-001")["status"]=="review"
    assert fixture_identity(left + " kalem 002",left,
                            "DEMO-M512-001")["status"]=="review"


def test_m431_evidence_contains_quote_and_valid_sha():
    good=analyze(_description(1),"m³",_description(1),"m³",
                 source_refs={"catalog":{"position_code":"DEMO-M512-001"}})
    bad=analyze(_description(1),"m³",_description(2),"m³",
                source_refs={"catalog":{"position_code":"DEMO-M512-002"}})
    assert verify_evidence(good) and verify_evidence(bad)
    assert good["status"]=="compatible" and good["approval_allowed"]
    assert len([c for c in good["checks"] if c["key"]=="fixture_item_identity"])==1
    assert bad["status"]=="blocked" and not bad["approval_allowed"]
    assert "M512_ITEM_ID_MISMATCH" in bad["blockers"]
    assert approval_identity_issue(_description(1),_description(1),"DEMO-M512-001",good) is None
    assert approval_identity_issue(_description(1),_description(1),"DEMO-M512-001",
                                  {"checks":[]})=="M512_IDENTITY_EVIDENCE_MISSING"


def test_m431_100_rows_100_positions_wrong_candidates_blocked(client,monkeypatch):
    head,pid,cat=_prepare(client,monkeypatch)
    _run(client,head,pid,cat)
    summary=client.get(f"/api/projects/{pid}/m42/queue",headers=head,
                       params={"page_size":50}).json()
    assert summary["run"]["row_count"]==100
    assert summary["run"]["candidate_count"]==300
    assert summary["total"]==300
    assert summary["summary"]["statuses"]["compatible"]==100
    assert summary["summary"]["statuses"]["blocked"]==200
    assert summary["summary"]["decisions"]["approved"]==0
    candidates=summary["rows"]
    matching=[r for r in candidates if r["code"]=="DEMO-M512-001"]
    assert matching and matching[0]["source_row"]==2
    assert matching[0]["can_approve"] and matching[0]["identity_issue"] is None
    wrong=[r for r in candidates if r["source_row"]==2 and r["code"]!="DEMO-M512-001"]
    assert len(wrong)==2 and all(not r["can_approve"] for r in wrong)
    assert all(r["identity_issue"]=="M512_ITEM_ID_MISMATCH" for r in wrong)
    detail=client.get(f"/api/projects/{pid}/m42/candidates/{wrong[0]['candidate_id']}",
                      headers=head).json()
    assert detail["evidence"]["status"]=="blocked"
    assert not detail["can_approve"]
    assert any(x["key"]=="fixture_item_identity" for x in detail["evidence"]["checks"])


def test_m431_published_old_evidence_cannot_be_approved(client,monkeypatch):
    head,pid,cat=_prepare(client,monkeypatch)
    # Simulate prior worker run, when fixture identity rule did not yet exist.
    with monkeypatch.context() as legacy:
        legacy.setattr(evidence_v41,"fixture_identity",lambda *args,**kwargs:None)
        old=_run(client,head,pid,cat)
    initial=client.get(f"/api/projects/{pid}/m42/queue",headers=head,
                       params={"page_size":20}).json()
    assert initial["summary"]["statuses"]["compatible"]==300
    assert all(not r["can_approve"] for r in initial["rows"])
    for row in initial["rows"]:
        correct_code = f"DEMO-M512-{row['source_row'] - 1:03d}"
        expected = ("M512_IDENTITY_EVIDENCE_MISSING"
                    if row["code"] == correct_code else "M512_ITEM_ID_MISMATCH")
        assert row["identity_issue"] == expected
    original=initial["rows"][0]
    denial=client.post(f"/api/projects/{pid}/m2/decisions",headers=head,json={
        "run_id":old["run_id"],"candidate_id":original["candidate_id"],
        "action":"approve","reason":"Tried to trust an obsolete technical evidence snapshot"})
    assert denial.status_code==409,denial.text
    # Re-running same intact Excel replaces the *current run* only; previous
    # immutable audit evidence is not deleted.
    new=_run(client,head,pid,cat)
    assert new["run_id"]!=old["run_id"]
    after=client.get(f"/api/projects/{pid}/m42/queue",headers=head).json()
    assert after["summary"]["statuses"]["compatible"]==100
    assert after["summary"]["statuses"]["blocked"]==200
    assert after["summary"]["decisions"]["approved"]==0
