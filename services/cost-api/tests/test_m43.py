"""M4.3 local bulk job acceptance: durable chunk progress and 100/250/500 rows."""
from datetime import datetime,timedelta
from io import BytesIO
from time import perf_counter
from uuid import uuid4
import pytest
from openpyxl import Workbook
from sqlalchemy import select
from test_m41 import auth,project_and_catalog,grant
from app.models import BulkJob,MatchCandidate,MatchDecision,MatchRun,WorkItem
from app.database import get_db
from app import catalog_operator
from app import m43_worker


def session_for(client):
    g=client.app.dependency_overrides[get_db]()
    db=next(g)
    return db,g


def fixture(client,monkeypatch,rows=5,email="m43@example.com"):
    headers=auth(client,"M43 Demo "+email,email)
    project_id,catalog=project_and_catalog(client,headers)
    if rows!=1:
        wb=Workbook();s=wb.active
        s.append(["İmalat Açıklaması","Miktar","Birim"])
        for _ in range(rows):
            s.append(["Hazır beton döküm C25/30 nakliye dahildir","7,5","m3"])
        out=BytesIO();wb.save(out)
        uploaded=client.post(f"/api/projects/{project_id}/imports",headers=headers,
            files={"file":("batch.xlsx",out.getvalue())})
        assert uploaded.status_code==201,uploaded.text
        assert uploaded.json()["row_count"]==rows
    grant(client,monkeypatch,catalog["id"])
    return headers,project_id,catalog


def enqueue(client,headers,project,catalog,key=None):
    return client.post(f"/api/projects/{project}/m43/jobs",headers=headers,json={
        "version_id":catalog["version_id"],
        "idempotency_key":key or str(uuid4())})


def status(client,headers,project,job_id):
    r=client.get(f"/api/projects/{project}/m43/jobs/{job_id}",headers=headers)
    assert r.status_code==200,r.text
    return r.json()


def step(client,job,chunk=20):
    db,g=session_for(client)
    try:return m43_worker.process_chunk(db,job,chunk_size=chunk)
    finally:g.close()


def test_enqueue_idempotency_and_worker_restart(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,45)
    key=str(uuid4())
    start=enqueue(client,head,pid,catalog,key)
    assert start.status_code==202,start.text
    job=start.json()
    assert job["status"]=="queued"
    assert job["total_rows"]==45
    assert status(client,head,pid,job["id"])["processed_rows"]==0
    assert enqueue(client,head,pid,catalog,key).json()["id"]==job["id"]
    assert enqueue(client,head,pid,catalog).status_code==409
    assert client.get(f"/api/projects/{pid}/m42/queue",headers=head).json()["run"] is None
    assert step(client,job["id"],chunk=20)
    partial=status(client,head,pid,job["id"])
    assert partial["processed_rows"]==20 and partial["status"]=="queued"
    assert partial["published"] is False
    # New session, simulating application/worker restart, keeps exact cursor.
    assert step(client,job["id"],chunk=20)
    assert status(client,head,pid,job["id"])["processed_rows"]==40
    assert step(client,job["id"],chunk=20)
    final=status(client,head,pid,job["id"])
    assert final["status"]=="completed"
    assert final["processed_rows"]==45 and final["percent"]==100
    assert final["candidate_count"]==135 and final["published"]
    assert not step(client,job["id"])
    queue=client.get(f"/api/projects/{pid}/m42/queue",headers=head,params={
        "page_size":50,"page":1})
    assert queue.status_code==200,queue.text
    assert queue.json()["total"]==135
    assert queue.json()["rows"][0]["source_row"]==2
    assert queue.json()["run"]["candidate_count"]==135
    db,g=session_for(client)
    try:
        run=db.get(MatchRun,job["run_id"])
        assert run.candidate_count==135
        candidates=db.scalars(select(MatchCandidate).where(
            MatchCandidate.run_id==run.id)).all()
        assert len(candidates)==len(set((x.work_item_id,x.rank) for x in candidates))
    finally:g.close()


def test_permission_revocation_blocks_publish_and_retry(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,30,email="revoke43@example.com")
    start=enqueue(client,head,pid,catalog)
    assert start.status_code==202
    job=start.json()
    assert step(client,job["id"],chunk=20)
    catalog_operator.record_review(catalog["id"],"M43 operator",
        b"Synthetic rights revoked between bulk chunks",
        "Withdrawal of permission for regression test","revoke")
    assert step(client,job["id"],chunk=20)
    blocked=status(client,head,pid,job["id"])
    assert blocked["status"]=="blocked" and blocked["processed_rows"]==20
    assert blocked["published"] is False
    assert not step(client,job["id"])
    assert client.post(f"/api/projects/{pid}/m43/jobs/{job['id']}/retry",
                       headers=head).status_code==409
    assert client.get(f"/api/projects/{pid}/m42/queue",headers=head).json()["run"] is None


def test_failure_retry_and_expired_lease(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,25,email="retry43@example.com")
    job=enqueue(client,head,pid,catalog).json()
    db,g=session_for(client)
    try:
        obj=db.get(BulkJob,job["id"])
        obj.status="running";obj.lease_owner=str(uuid4())
        obj.lease_until=datetime.utcnow()+timedelta(minutes=20)
        db.commit()
    finally:g.close()
    assert not step(client,job["id"])
    db,g=session_for(client)
    try:
        obj=db.get(BulkJob,job["id"])
        obj.lease_until=datetime.utcnow()-timedelta(minutes=1)
        db.commit()
    finally:g.close()
    original=m43_worker.similarity
    def fail_once(*args,**kw):
        raise RuntimeError("Simulated transient failure")
    monkeypatch.setattr(m43_worker,"similarity",fail_once)
    assert step(client,job["id"])
    failed=status(client,head,pid,job["id"])
    assert failed["status"]=="failed" and failed["processed_rows"]==0
    assert failed["failure_reason"]=="RuntimeError"
    monkeypatch.setattr(m43_worker,"similarity",original)
    retried=client.post(f"/api/projects/{pid}/m43/jobs/{job['id']}/retry",headers=head)
    assert retried.status_code==202,retried.text
    assert step(client,job["id"])
    assert step(client,job["id"])
    final=status(client,head,pid,job["id"])
    assert final["status"]=="completed" and final["candidate_count"]==75
    assert enqueue(client,head,pid,catalog,job["id"]).status_code==202


def test_tenant_isolation_and_bad_limits(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,7,email="owner43@example.com")
    other=auth(client,"Other org","outsider43@example.com")
    assert client.get(f"/api/projects/{pid}/m43/catalogs",headers=other).status_code==404
    assert enqueue(client,other,pid,catalog).status_code==404
    jobs=client.get(f"/api/projects/{pid}/m43/jobs",headers=head)
    assert jobs.status_code==200 and jobs.json()==[]
    start=enqueue(client,head,pid,catalog)
    job=start.json()
    assert client.get(f"/api/projects/{pid}/m43/jobs/{job['id']}",headers=other).status_code==404
    assert client.post(f"/api/projects/{pid}/m43/jobs/{job['id']}/retry",headers=other).status_code==404
    assert client.post(f"/api/projects/{pid}/m43/jobs/{job['id']}/retry",headers=head).status_code==409


@pytest.mark.parametrize("rows",[100,250,500])
def test_synthetic_volume_and_complete_safe_review(client,monkeypatch,rows):
    headers,pid,catalog=fixture(client,monkeypatch,rows,email=f"volume{rows}@example.com")
    queued=enqueue(client,headers,pid,catalog)
    assert queued.status_code==202,queued.text
    job=queued.json()
    started=perf_counter()
    # Process in DB transactions of max 20 work-item rows.
    for _ in range((rows+19)//20):
        assert step(client,job["id"])
    elapsed=perf_counter()-started
    done=status(client,headers,pid,job["id"])
    assert done["processed_rows"]==rows
    assert done["candidate_count"]==rows*3
    assert done["status"]=="completed"
    assert done["percent"]==100
    listing=client.get(f"/api/projects/{pid}/m42/queue",headers=headers,
                       params={"page_size":50,"page":1})
    assert listing.status_code==200,listing.text
    assert listing.json()["total"]==rows*3
    assert len(listing.json()["rows"])==50
    assert listing.json()["summary"]["statuses"]["blocked"]==rows*2
    assert listing.json()["summary"]["statuses"]["compatible"]==rows
    assert listing.json()["summary"]["decisions"]["approved"]==0
    # Historical human decisions are not fabricated.
    one=client.get(f"/api/projects/{pid}/m42/queue",headers=headers,
                   params={"status":"compatible","page_size":10}).json()["rows"][0]
    assert one["can_approve"] is True
    print(f"M43_VOLUME_METRIC rows={rows} candidates={rows*3} seconds={elapsed:.3f}")


def test_pending_job_blocks_other_matching_routes(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,15,email="nointerleave43@example.com")
    start=enqueue(client,head,pid,catalog)
    assert start.status_code==202
    assert client.post(f"/api/projects/{pid}/m41/run",headers=head).status_code==409
    assert client.post(f"/api/projects/{pid}/m21/rematch",headers=head).status_code==409
    assert client.post(f"/api/m3/projects/{pid}/run",headers=head,
        json={"version_id":catalog["version_id"]}).status_code==409


def test_500_metraj_x_500_catalog_positions(client,monkeypatch):
    # A genuine licensed-gate-shaped, fictional fixture: no database mutation
    # after approval and no official catalog data.
    from time import perf_counter
    head,pid,_old=fixture(client,monkeypatch,500,email="stress43@example.com")
    synthetic=("Poz Kodu;Poz Tanımı;Birim\n"+
        "".join(
          f"P-{i:04d};Hazır beton döküm C25/30 nakliye dahildir özel {i:04d};m³\n"
          for i in range(500)
        )).encode("utf-8-sig")
    staged=client.post("/api/m3/imports",headers=head,
        data={"institution":"OTHER","year":"2026","period":"M43-STRESS500"},
        files={"file":("stress500.csv",synthetic)})
    assert staged.status_code==201,staged.text
    catalog=staged.json()
    grant(client,monkeypatch,catalog["id"])
    started=perf_counter()
    first=enqueue(client,head,pid,catalog)
    assert first.status_code==202,first.text
    job=first.json()
    for _ in range(25):
        assert step(client,job["id"])
    elapsed=perf_counter()-started
    done=status(client,head,pid,job["id"])
    assert done["status"]=="completed"
    assert done["processed_rows"]==500
    assert done["candidate_count"]==1500
    assert client.get(f"/api/projects/{pid}/m42/queue",headers=head).json()["total"]==1500
    print(f"M43_STRESS rows=500 positions=500 seconds={elapsed:.3f}")
