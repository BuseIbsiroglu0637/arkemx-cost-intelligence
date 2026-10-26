"""M5.2.1: cancel only queued, quarantine source without deletion, select baseline."""
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy import select
from app.database import get_db
from app.models import BulkJob, ImportBatch, WorkItem, M43QueueControlEvent, MetrajImportExclusion
from app import m43_worker
from test_m43 import fixture, enqueue, step, status
from test_m52 import base, xlsx, ORIGINAL
from test_m41 import auth


def operator(client, pid, head, suffix):
    return f"/api/projects/{pid}/m521/{suffix}"


def reason(text="Incorrect source import requires review before processing"):
    return {"reason": text}


def test_m521_cancel_queued_is_idempotent_and_worker_cannot_claim(client, monkeypatch):
    head, pid, catalog = fixture(client, monkeypatch, 4, email="m521cancel@example.com")
    run = enqueue(client, head, pid, catalog).json()
    assert run["status"] == "queued"
    url = operator(client,pid,head,f"jobs/{run['id']}/cancel")
    response = client.post(url, headers=head, json=reason())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "blocked" and data["cancelled"]
    assert data["idempotent"] is False
    assert not step(client,run["id"])
    repeat = client.post(url, headers=head, json=reason()).json()
    assert repeat["idempotent"] is True
    assert status(client,head,pid,run["id"])["published"] is False
    assert client.get(f"/api/projects/{pid}/m42/queue",headers=head).json()["run"] is None
    rows = client.get(operator(client,pid,head,"jobs"),headers=head)
    assert rows.status_code == 200 and rows.json()[0]["cancelled_by_operator"]
    assert rows.json()[0]["cancel_reason"].startswith("Incorrect source")
    assert len(client.get(f"/api/projects/{pid}/m521/imports",headers=head).json()) >= 1
    g=client.app.dependency_overrides[get_db]();db=next(g)
    assert db.scalar(select(M43QueueControlEvent).where(M43QueueControlEvent.job_id == run["id"]))
    assert db.scalar(select(ImportBatch).where(ImportBatch.id == run["import_id"]))
    g.close()


def test_m521_running_lease_cannot_be_cancelled(client, monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,3,email="m521running@example.com")
    run=enqueue(client,head,pid,catalog).json()
    g=client.app.dependency_overrides[get_db]();db=next(g)
    job=db.get(BulkJob,run["id"])
    job.status="running"
    job.lease_owner="ef23e320-3454-4585-baf2-999a14748343"
    db.commit();g.close()
    url=operator(client,pid,head,f"jobs/{run['id']}/cancel")
    denied=client.post(url,headers=head,json=reason())
    assert denied.status_code==409
    assert client.get(operator(client,pid,head,"jobs"),headers=head).json()[0]["status"]=="running"


def test_m521_exclude_preserves_uploaded_rows_and_blocks_new_m43(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,1,email="m521exclude@example.com")
    batch=client.get(f"/api/projects/{pid}/imports",headers=head).json()[0]
    action=operator(client,pid,head,f"imports/{batch['id']}/exclude")
    res=client.post(action,headers=head,json=reason("The source has unreadable characters and invalid unit data"))
    assert res.status_code==200,res.text
    assert res.json()["excluded"] is True
    second=client.post(action,headers=head,json=reason())
    assert second.status_code==200 and second.json()["idempotent"] is True
    assert enqueue(client,head,pid,catalog).status_code==409
    imports=client.get(operator(client,pid,head,"imports"),headers=head).json()
    assert imports[0]["excluded"] and imports[0]["sha256"]==batch["sha256"]
    assert client.get(f"/api/projects/{pid}/imports",headers=head).json()[0]["sha256"]==batch["sha256"]
    g=client.app.dependency_overrides[get_db]();db=next(g)
    assert db.get(MetrajImportExclusion,batch["id"])
    assert db.scalar(select(WorkItem).where(WorkItem.import_id==batch["id"]))
    g.close()


def test_m521_active_job_blocks_exclusion_until_cancelled(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,1,email="m521act@example.com")
    run=enqueue(client,head,pid,catalog).json()
    url=operator(client,pid,head,f"imports/{run['import_id']}/exclude")
    assert client.post(url,headers=head,json=reason()).status_code==409
    assert client.post(operator(client,pid,head,f"jobs/{run['id']}/cancel"),
        headers=head,json=reason()).status_code==200
    assert client.post(url,headers=head,json=reason()).status_code==200
    assert not step(client,run["id"])


def test_m521_tenant_authorization_and_blank_reason(client,monkeypatch):
    head,pid,catalog=fixture(client,monkeypatch,1,email="m521tenant@example.com")
    run=enqueue(client,head,pid,catalog).json()
    outsider=auth(client,"Unrelated tenant office","m521another@example.com")
    job_url=operator(client,pid,head,f"jobs/{run['id']}/cancel")
    import_url=operator(client,pid,head,f"imports/{run['import_id']}/exclude")
    assert client.post(job_url,headers=outsider,json=reason()).status_code==404
    assert client.post(import_url,headers=outsider,json=reason()).status_code==404
    assert client.get(operator(client,pid,head,"imports"),headers=outsider).status_code==404
    assert client.get(operator(client,pid,head,"jobs"),headers=outsider).status_code==404
    assert client.post(job_url,headers=head,json=reason("          ")).status_code==422
    assert client.post(import_url,headers=head,json=reason("          ")).status_code==422
    assert client.get(operator(client,pid,head,"jobs"),headers=head).json()[0]["status"]=="queued"


def test_m521_explicit_historical_metraj_preview_is_readonly(client,monkeypatch):
    head,pid,estimate_id=base(client,monkeypatch)
    imports=client.get(operator(client,pid,head,"imports"),headers=head).json()
    old_id=imports[0]["id"]
    damaged=xlsx([("Haz?r beton d?k?m C25/30 nakliye dahildir",13,None)])
    create=client.post(f"/api/projects/{pid}/imports",headers=head,
        files={"file":("bad-r02.xlsx",damaged)})
    assert create.status_code==201,create.text
    latest=create.json()["id"]
    good=xlsx([(ORIGINAL,13,"m3")])
    url=f"/api/projects/{pid}/m52/preview"
    res=client.post(url,headers=head,
        data={"baseline_import_id":old_id,"estimate_id":estimate_id},
        files={"file":("good-r02.xlsx",good)})
    assert res.status_code==200,res.text
    p=res.json()
    assert p["baseline_import_id"]==old_id
    assert p["latest_import_id"]==latest
    assert p["baseline_is_current"] is False
    assert p["apply_allowed"] is False
    assert p["known_quantity_effect"]=="625.00"
    # Wrong historical import with an unrelated M5 estimate is rejected.
    wrong=client.post(url,headers=head,
        data={"baseline_import_id":latest,"estimate_id":estimate_id},
        files={"file":("good-r02.xlsx",good)})
    assert wrong.status_code==409
    assert len(client.get(f"/api/projects/{pid}/imports",headers=head).json())==2


def test_m521_excluded_latest_does_not_reactivate_historical_approvals(client,monkeypatch):
    head,pid,estimate_id=base(client,monkeypatch)
    source=client.get(f"/api/projects/{pid}/imports",headers=head).json()[0]
    # A valid historical M4.3 + M4.2 approval is present.
    before=client.get(f"/api/projects/{pid}/m5/eligible",headers=head)
    assert before.status_code==200,before.text
    action=operator(client,pid,head,f"imports/{source['id']}/exclude")
    assert client.post(action,headers=head,json=reason("Source requires engineering review before further use")).status_code==200
    # After explicit exclusion old approvals cannot be used to create fresh prices.
    ineligible=client.get(f"/api/projects/{pid}/m5/eligible",headers=head)
    assert ineligible.status_code==409,ineligible.text
    # Recorded historic evidence is still readable.
    old=client.get(f"/api/projects/{pid}/m5/estimates/{estimate_id}",headers=head)
    assert old.status_code==200
    assert old.json()["total"]=="15625.00"
    # A properly selected historical M5 reference is previewable, but non-applicable.
    revised=xlsx([(ORIGINAL,13,"m3")])
    view=client.post(f"/api/projects/{pid}/m52/preview",headers=head,
       data={"estimate_id":estimate_id},files={"file":("r02.xlsx",revised)})
    assert view.status_code==200,view.text
    assert view.json()["baseline_excluded"] is True
    assert view.json()["apply_allowed"] is False
    assert view.json()["known_quantity_effect"]=="625.00"
