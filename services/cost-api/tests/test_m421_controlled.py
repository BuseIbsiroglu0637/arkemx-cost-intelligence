"""M4.2.1: each staged decision remains a separately verified human approval.

No server-side mass approval. One request writes at most one M2 decision.
"""
from test_m42 import ready, queue
from test_m41 import auth
from app.database import get_db
from app.models import WorkItem
from sqlalchemy import select


def detail(client,pid,head,candidate_id):
    return client.get(f"/api/projects/{pid}/m42/candidates/{candidate_id}",
                      headers=head)


def review(client,pid,head,run_id,candidate_id,evidence_sha256,
           reason="Synthetic engineering evidence reviewed individually",
           confirmation="I_REVIEWED_THIS_CANDIDATE_EVIDENCE"):
    return client.post(f"/api/projects/{pid}/m42/controlled-decisions",headers=head,
        json={"run_id":run_id,"candidate_id":candidate_id,
              "evidence_sha256":evidence_sha256,"reason":reason,
              "confirmation":confirmation})


def test_controlled_review_creates_one_audited_human_decision(client,monkeypatch):
    head,pid,cat,run=ready(client,monkeypatch)
    candidate=queue(client,pid,head,status="compatible",decision="undecided").json()["rows"][0]
    evidence=detail(client,pid,head,candidate["candidate_id"]).json()["evidence"]
    before=queue(client,pid,head).json()["summary"]["decisions"]
    assert before["approved"]==0
    result=review(client,pid,head,run,candidate["candidate_id"],evidence["evidence_sha256"])
    assert result.status_code==201,result.text
    body=result.json()
    assert body["confirmed_evidence_sha256"]==evidence["evidence_sha256"]
    assert body["approved_automatically"] is False
    assert body["confirmation_recorded"] is True
    after=queue(client,pid,head).json()["summary"]["decisions"]
    assert after["approved"]==1
    assert after["undecided"]==before["undecided"]-1
    row=detail(client,pid,head,candidate["candidate_id"]).json()
    assert row["history"][0]["action"]=="approve"
    assert row["history"][0]["reason"]=="Synthetic engineering evidence reviewed individually"
    assert row["history"][0]["current_run"]
    repeat=review(client,pid,head,run,candidate["candidate_id"],evidence["evidence_sha256"])
    assert repeat.status_code==409


def test_controlled_review_blocks_wrong_sha_bad_consent_short_reason_and_wrong_run(client,monkeypatch):
    head,pid,cat,run=ready(client,monkeypatch)
    candidate=queue(client,pid,head,status="compatible").json()["rows"][0]
    cid=candidate["candidate_id"]
    digest=detail(client,pid,head,cid).json()["evidence"]["evidence_sha256"]
    assert review(client,pid,head,run,cid,"f"*64).status_code==409
    assert review(client,pid,head,run,cid,digest,confirmation="NO").status_code==422
    assert review(client,pid,head,run,cid,digest,reason="short").status_code==422
    assert review(client,pid,head,run,cid,digest,reason="           ").status_code==422
    assert review(client,pid,head,"0"*36,cid,digest).status_code==409
    assert queue(client,pid,head).json()["summary"]["decisions"]["approved"]==0


def test_controlled_review_rejects_blocked_candidates_and_other_tenants(client,monkeypatch):
    head,pid,cat,run=ready(client,monkeypatch)
    outsider=auth(client,"M421 Another Tenant","m421other@example.com")
    compatible=queue(client,pid,head,status="compatible").json()["rows"][0]
    cid=compatible["candidate_id"]
    digest=detail(client,pid,head,cid).json()["evidence"]["evidence_sha256"]
    assert review(client,pid,outsider,run,cid,digest).status_code==404
    blocked=queue(client,pid,head,status="blocked").json()["rows"][0]
    digest2=detail(client,pid,head,blocked["candidate_id"]).json()["evidence"]["evidence_sha256"]
    assert review(client,pid,head,run,blocked["candidate_id"],digest2).status_code==409
    assert queue(client,pid,head).json()["summary"]["decisions"]["approved"]==0


def test_controlled_review_rejects_stale_sources_without_new_approval(client,monkeypatch):
    head,pid,cat,run=ready(client,monkeypatch)
    candidate=queue(client,pid,head,status="compatible").json()["rows"][0]
    cid=candidate["candidate_id"]
    digest=detail(client,pid,head,cid).json()["evidence"]["evidence_sha256"]
    gen=client.app.dependency_overrides[get_db]()
    db=next(gen)
    gen.close()
    # New import is enough to make the M4 run stale without altering old rows.
    from io import BytesIO
    from openpyxl import Workbook
    workbook=Workbook();ws=workbook.active
    ws.append(["İmalat Açıklaması","Miktar","Birim"])
    ws.append(["Yeni test kapsamı C30/37",2,"m3"])
    result=BytesIO();workbook.save(result)
    response=client.post(f"/api/projects/{pid}/imports",headers=head,
           files={"file":("m421-changed-source.xlsx",result.getvalue())})
    assert response.status_code==201,response.text
    assert review(client,pid,head,run,cid,digest).status_code==409
    assert queue(client,pid,head).json()["summary"]["decisions"]["approved"]==0


def test_controlled_review_tampered_evidence_fails_closed(client,monkeypatch):
    head,pid,cat,run=ready(client,monkeypatch)
    candidate=queue(client,pid,head,status="compatible").json()["rows"][0]
    cid=candidate["candidate_id"]
    digest=detail(client,pid,head,cid).json()["evidence"]["evidence_sha256"]
    gen=client.app.dependency_overrides[get_db]();db=next(gen)
    from app.models import TechnicalEvidence
    proof=db.scalar(select(TechnicalEvidence).where(TechnicalEvidence.candidate_id==cid))
    proof.evidence_sha256="0"*64
    db.commit();gen.close()
    assert review(client,pid,head,run,cid,digest).status_code==409
