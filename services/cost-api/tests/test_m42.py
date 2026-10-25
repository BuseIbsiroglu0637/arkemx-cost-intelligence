"""M4.2 review-queue contract tests: server pagination, rights, history and gates."""
from io import BytesIO
from openpyxl import Workbook
from test_m41 import auth, project_and_catalog, grant
from app import catalog_operator
from app.database import get_db
from app.models import WorkItemRevision, User
from sqlalchemy import select


def ready(client,monkeypatch):
    head=auth(client,"Review 4.2","m42pilot@example.com")
    pid,catalog=project_and_catalog(client,head)
    grant(client,monkeypatch,catalog["id"])
    assert client.post(f"/api/m3/projects/{pid}/run",headers=head,
        json={"version_id":catalog["version_id"]}).status_code==201
    run=client.post(f"/api/projects/{pid}/m41/run",headers=head)
    assert run.status_code==201,run.text
    return head,pid,catalog,run.json()["id"]


def queue(client,pid,head,**params):
    return client.get(f"/api/projects/{pid}/m42/queue",headers=head,params=params)


def test_summary_filter_decision_history(client,monkeypatch):
    head,pid,catalog,run_id=ready(client,monkeypatch)
    first=queue(client,pid,head)
    assert first.status_code==200,first.text
    data=first.json()
    assert data["run"]["id"]==run_id
    assert data["run"]["row_limit"]==100
    assert data["run"]["catalog_position_limit"]==500
    assert data["total"]==3
    assert data["summary"]["statuses"]["blocked"]==2
    assert data["summary"]["statuses"]["compatible"]==1
    assert data["summary"]["decisions"]["undecided"]==3
    compatible=queue(client,pid,head,status="compatible")
    assert compatible.json()["total"]==1
    candidate=compatible.json()["rows"][0]
    assert candidate["can_approve"] is True
    assert candidate["code"]=="DEMO-C25"
    blocked=queue(client,pid,head,status="blocked")
    assert blocked.json()["total"]==2
    assert all(not c["can_approve"] for c in blocked.json()["rows"])
    matches=queue(client,pid,head,q="demo-c25")
    assert matches.json()["total"]==1
    assert queue(client,pid,head,q="%").json()["total"]==0
    assert queue(client,pid,head,status="missing").json()["total"]==0
    assert queue(client,pid,head,decision="approved").json()["total"]==0
    detail=client.get(f"/api/projects/{pid}/m42/candidates/{candidate['candidate_id']}",headers=head)
    assert detail.status_code==200,detail.text
    assert detail.json()["evidence"]["source_refs"]["catalog"]["position_code"]=="DEMO-C25"
    assert detail.json()["history"]==[]
    action=client.post(f"/api/projects/{pid}/m2/decisions",headers=head,json={
        "run_id":run_id,"candidate_id":candidate["candidate_id"],"action":"approve",
        "reason":"Technical and rights checks performed, synthetic pilot"})
    assert action.status_code==201,action.text
    approved=queue(client,pid,head,decision="approved")
    assert approved.status_code==200,approved.text
    assert approved.json()["total"]==1
    assert approved.json()["summary"]["decisions"]["approved"]==1
    assert queue(client,pid,head,decision="undecided").json()["total"]==2
    refreshed=client.get(f"/api/projects/{pid}/m42/candidates/{candidate['candidate_id']}",headers=head)
    assert refreshed.json()["history"][0]["current_run"] is True
    assert refreshed.json()["history"][0]["reason"].startswith("Technical and rights")
    # Rejection is an explicit new event, never deletes previous approval.
    reject=client.post(f"/api/projects/{pid}/m2/decisions",headers=head,json={
        "run_id":run_id,"candidate_id":candidate["candidate_id"],
        "action":"reject","reason":"After review, not approved as a final position"})
    assert reject.status_code==201
    assert queue(client,pid,head,decision="approved").json()["total"]==0
    assert queue(client,pid,head,decision="rejected").json()["total"]==1
    again=client.get(f"/api/projects/{pid}/m42/candidates/{candidate['candidate_id']}",headers=head).json()
    assert len(again["history"])==2
    assert again["history"][0]["action"]=="reject"
    assert again["history"][1]["action"]=="approve"


def test_search_and_server_pagination(client,monkeypatch):
    head=auth(client,"M42 Paging","m42paging@example.com")
    pid,catalog=project_and_catalog(client,head)
    # Replace latest import with 40 synthetic work-items, leaving original untouched.
    book=Workbook();sheet=book.active
    sheet.append(["İmalat Açıklaması","Miktar","Birim"])
    for _ in range(40):
        sheet.append(["Hazır beton döküm C25/30 nakliye dahildir","7,5","m3"])
    out=BytesIO();book.save(out)
    response=client.post(f"/api/projects/{pid}/imports",headers=head,
        files={"file":("batch40.xlsx",out.getvalue())})
    assert response.status_code==201,response.text
    grant(client,monkeypatch,catalog["id"])
    assert client.post(f"/api/m3/projects/{pid}/run",headers=head,
        json={"version_id":catalog["version_id"]}).status_code==201
    run=client.post(f"/api/projects/{pid}/m41/run",headers=head)
    assert run.status_code==201,run.text
    total=queue(client,pid,head,page=1,page_size=50).json()
    assert total["total"]==120
    assert len(total["rows"])==50
    assert len({x["candidate_id"] for x in total["rows"]})==50
    second=queue(client,pid,head,page=2,page_size=50).json()
    third=queue(client,pid,head,page=3,page_size=50).json()
    assert len(second["rows"])==50 and len(third["rows"])==20
    assert not ({x["candidate_id"] for x in total["rows"]} & {x["candidate_id"] for x in second["rows"]})
    assert queue(client,pid,head,page=4,page_size=50).json()["rows"]==[]
    assert queue(client,pid,head,page_size=51).status_code==422
    assert queue(client,pid,head,page=0).status_code==422
    assert queue(client,pid,head,status="review").json()["total"]==0
    assert queue(client,pid,head,status="blocked").json()["total"]==80
    assert queue(client,pid,head,status="compatible").json()["total"]==40
    assert queue(client,pid,head,q="demO-no").json()["total"]==40
    assert queue(client,pid,head,q="no-such-code").json()["total"]==0


def test_isolation_revocation_and_stale_metraj(client,monkeypatch):
    a,pid,catalog,run=ready(client,monkeypatch)
    b=auth(client,"Separate Office","m42separate@example.com")
    assert queue(client,pid,b).status_code==404
    first=queue(client,pid,a,status="compatible").json()["rows"][0]
    assert client.get(f"/api/projects/{pid}/m42/candidates/{first['candidate_id']}",headers=b).status_code==404
    assert client.get(f"/api/projects/{pid}/m42/candidates/00000000-0000-0000-0000-000000000000",headers=a).status_code==404
    # Prevent approving stale prior work after a correction.
    override=client.app.dependency_overrides[get_db]
    gen=override();db=next(gen)
    from app.models import WorkItem
    work=db.scalar(select(WorkItem).where(WorkItem.id==first["work_item_id"]))
    original_quantity=work.quantity
    db.add(WorkItemRevision(
        work_item_id=work.id,revision=1,description="Hazır beton döküm C30/37 nakliye dahildir",
        quantity=original_quantity,unit="m³",corrected_by_id=db.scalar(select(User).where(User.email=="m42pilot@example.com")).id,
        reason="Revision of concrete grade for stale-run test"
    ))
    db.commit();gen.close()
    after=queue(client,pid,a,status="compatible").json()["rows"][0]
    assert after["stale"] is True
    assert after["can_approve"] is False
    assert client.post(f"/api/projects/{pid}/m2/decisions",headers=a,json={
        "run_id":run,"candidate_id":first["candidate_id"],"action":"approve",
        "reason":"Attempt stale approval"}).status_code==409
    # Rights revocation also disables independent candidate review.
    catalog_operator.record_review(catalog["id"],"M42 operator",
        b"Data use permission deliberately revoked for independent test in M42",
        "Separate synthetic dataset permission revoked for security regression", "revoke")
    revoked=queue(client,pid,a,status="compatible").json()
    assert revoked["run"]["rights_active"] is False
    assert revoked["rows"][0]["can_approve"] is False
    assert client.post(f"/api/projects/{pid}/m41/run",headers=a).status_code==403
    assert client.post(f"/api/projects/{pid}/m2/decisions",headers=a,json={
        "run_id":run,"candidate_id":first["candidate_id"],"action":"approve",
        "reason":"Attempt revoked approval"}).status_code==403


def test_evidence_tamper_must_fail_closed(client,monkeypatch):
    head,pid,catalog,run=ready(client,monkeypatch)
    candidate=queue(client,pid,head).json()["rows"][0]
    gen=client.app.dependency_overrides[get_db]();db=next(gen)
    from app.models import TechnicalEvidence
    entry=db.scalar(select(TechnicalEvidence).where(
        TechnicalEvidence.candidate_id==candidate["candidate_id"]))
    entry.evidence_sha256="0"*64
    db.commit();gen.close()
    assert queue(client,pid,head).status_code==409
    assert client.get(f"/api/projects/{pid}/m42/candidates/{candidate['candidate_id']}",headers=head).status_code==409
