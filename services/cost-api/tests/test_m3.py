"""M3 catalog import and independent operator approval acceptance tests.

All position data generated here is synthetic. No official codes or price lists.
"""
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from app.database import get_db
from app.models import CatalogImport
from app.catalog_operator import record_review, CONFIRM
from app import catalog_operator


def auth(client, name, email):
    result=client.post("/api/auth/register",json={
        "organization_name":name,"email":email,"password":"valid-pilot-password-123"})
    assert result.status_code==201,result.text
    return {"Authorization":"Bearer "+result.json()["access_token"]}


def csv_file():
    return ("Poz Kodu;Poz Tanımı;Birim;Birim Fiyat\n"
            "DEMO-SER-60;Porselen seramik kaplama 60x60;m²;980,50\n"
            "DEMO-GAZ-10;Gazbeton duvar 10 cm;m²;250,50\n").encode("utf-8-sig")


def spreadsheet(rows):
    book=Workbook();ws=book.active
    ws.append(["Poz Kodu","Poz Tanımı","Birim","Birim Fiyat"])
    for row in rows:ws.append(row)
    out=BytesIO();book.save(out)
    return out.getvalue()


def preview(client,headers,data):
    return client.post("/api/m3/preview",headers=headers,files={"file":("custom.csv",data)})


def stage(client,headers,data=None,period="2026-YILLIK",institution="CSB"):
    return client.post("/api/m3/imports",headers=headers,
        data={"institution":institution,"year":"2026","period":period,
              "source_url":"https://example.com/owned-catalog"},
        files={"file":("custom.csv",data or csv_file())})


def project(client,headers):
    res=client.post("/api/projects",headers=headers,json={"name":"M3 Sample Project"})
    assert res.status_code==201,res.text
    pid=res.json()["id"]
    wb=Workbook();s=wb.active
    s.append(["İmalat Açıklaması","Miktar","Birim"])
    s.append(["Porselen seramik kaplama 60x60","15,50","m2"])
    out=BytesIO();wb.save(out)
    saved=client.post(f"/api/projects/{pid}/imports",headers=headers,
                      files={"file":("metraj.xlsx",out.getvalue())})
    assert saved.status_code==201,saved.text
    return pid


def approve_local_operator(client,monkeypatch,import_id):
    override=client.app.dependency_overrides[get_db]
    session_generator=override()
    db=next(session_generator)
    try:
        monkeypatch.setattr(catalog_operator,"SessionLocal",sessionmaker(bind=db.get_bind()))
    finally:
        session_generator.close()
    return catalog_operator.record_review(
        import_id,"ARKEMX operator test",b"SYNTHETIC TEST DATA, WRITTEN BY THE TEST SUITE ONLY",
        "Invented fixture with permission for local testing",
        "approve",confirmation=CONFIRM
    )


def test_preview_staging_and_hash(client,auth):
    checked=preview(client,auth,csv_file())
    assert checked.status_code==200,checked.text
    assert checked.json()["row_count"]==2
    assert checked.json()["preview"][0]["code"]=="DEMO-SER-60"
    assert checked.json()["preview"][0]["price"]=="980.50"
    assert client.get("/api/m3/imports",headers=auth).json()==[]
    saved=stage(client,auth)
    assert saved.status_code==201,saved.text
    doc=saved.json()
    assert doc["institution"]=="CSB"
    assert doc["status"]=="pending" and not doc["approved"]
    assert len(doc["sha256"])==64
    assert len(client.get("/api/m3/imports",headers=auth).json())==1
    positions=client.get(f"/api/m3/imports/{doc['id']}/positions",headers=auth)
    assert positions.status_code==200
    assert len(positions.json()["positions"])==2
    assert stage(client,auth).status_code==409
    assert stage(client,auth,period="2026-2").status_code==201


def test_self_attestation_does_not_approve_staged_catalog(client,auth):
    doc=stage(client,auth).json()
    pid=project(client,auth)
    # Tenant-admin source 'verify' (M1) MUST NOT bypass operator's M3 gate.
    self_verified=client.post(f"/api/catalog/sources/{doc['source_id']}/verify",
         headers=auth,json={"license_evidence":"This is a self supplied statement",
                            "permission_scope":"Internal matching"})
    assert self_verified.status_code==200
    denied=client.post(f"/api/m3/projects/{pid}/run",
        headers=auth,json={"version_id":doc["version_id"]})
    assert denied.status_code==403
    assert client.get("/api/projects/"+pid+"/m2/latest",headers=auth).json()["run"] is None


def test_operator_approval_immutable_run_and_revocation(client,auth,monkeypatch):
    doc=stage(client,auth).json()
    pid=project(client,auth)
    approve_local_operator(client,monkeypatch,doc["id"])
    approved=client.get("/api/m3/imports",headers=auth).json()[0]
    assert approved["approved"] and approved["reviewed_by"]=="ARKEMX operator test"
    run=client.post(f"/api/m3/projects/{pid}/run",
        headers=auth,json={"version_id":doc["version_id"]})
    assert run.status_code==201,run.text
    assert run.json()["candidate_count"]>=1
    latest=client.get(f"/api/projects/{pid}/m2/latest",headers=auth).json()
    assert latest["run"]["source"]=="CSB"
    assert latest["run"]["catalog_period"]=="2026-YILLIK"
    assert not latest["run"]["synthetic"]
    assert latest["run"]["rights_active"]
    candidate=latest["items"][0]["candidates"][0]
    assert candidate["code"]=="DEMO-SER-60"
    assert candidate["approvable"]
    from app.models import CatalogReviewEvent
    from sqlalchemy import select
    override=client.app.dependency_overrides[get_db]
    gen=override();db=next(gen)
    try:
        count=len(db.scalars(select(CatalogReviewEvent)).all())
        assert count==1
    finally:gen.close()
    # An external operator may revoke previously licensed indexing.
    catalog_operator.record_review(
        doc["id"],"ARKEMX operator test",
        b"SYNTHETIC TEST DATA LICENCE REVOKED FOR EXERCISE",
        "Revoked data processing permission for this fixture","revoke"
    )
    current=client.get(f"/api/projects/{pid}/m2/latest",headers=auth).json()
    assert current["run"]["rights_active"] is False
    assert current["items"][0]["stale"] is True
    denied=client.post(f"/api/projects/{pid}/m2/decisions",
        headers=auth,json={"run_id":run.json()["id"],"candidate_id":candidate["id"],
                           "action":"approve"})
    assert denied.status_code==403
    blocked=client.post(f"/api/m3/projects/{pid}/run",
        headers=auth,json={"version_id":doc["version_id"]})
    assert blocked.status_code==403


def test_cross_tenant_catalog_isolation(client,monkeypatch):
    a=auth(client,"Office A","office-a-m3@example.com")
    b=auth(client,"Office B","office-b-m3@example.com")
    doc=stage(client,a).json()
    pb=project(client,b)
    assert client.get("/api/m3/imports",headers=b).json()==[]
    assert client.get(f"/api/m3/imports/{doc['id']}/positions",headers=b).status_code==404
    approve_local_operator(client,monkeypatch,doc["id"])
    denied=client.post(f"/api/m3/projects/{pb}/run",
        headers=b,json={"version_id":doc["version_id"]})
    assert denied.status_code==403


def test_validation_and_duplicate_csv_codes(client,auth):
    duplicated=("Poz Kodu;Poz Tanımı;Birim\nX-1;Seramik kaplama;m²\nX-1;Seramik duvar;m²\n").encode()
    bad=client.post("/api/m3/preview",headers=auth,files={"file":("bad.csv",duplicated)})
    assert bad.status_code==422
    no_price=("Poz Kodu;Poz Tanımı;Birim;Birim Fiyat\nX-1;Seramik kaplama;m²;1.234\n").encode()
    amb=client.post("/api/m3/preview",headers=auth,files={"file":("bad.csv",no_price)})
    assert amb.status_code==422
    formula=spreadsheet([["X-1", "=SUM(1,2)", "m²", 100]])
    failed=client.post("/api/m3/preview",headers=auth,files={"file":("bad.xlsx",formula)})
    assert failed.status_code==422
    assert client.get("/api/m3/imports",headers=auth).json()==[]


def test_custom_column_mapping_xlsx(client,auth):
    payload=spreadsheet([["DEMO-KAPI","İç kapı montajı","adet",245]])
    first=client.post("/api/m3/inspect",headers=auth,files={"file":("catalog.xlsx",payload)})
    assert first.status_code==200,first.text
    assert first.json()["suggested_mapping"]["code"]=="Poz Kodu"
    mapped=client.post("/api/m3/preview",headers=auth,files={"file":("catalog.xlsx",payload)})
    assert mapped.status_code==200,mapped.text
    assert mapped.json()["row_count"]==1


def test_operator_requires_explicit_evidence(client,auth,monkeypatch):
    doc=stage(client,auth).json()
    override=client.app.dependency_overrides[get_db]
    gen=override();db=next(gen)
    monkeypatch.setattr(catalog_operator,"SessionLocal",sessionmaker(bind=db.get_bind()))
    gen.close()
    import pytest
    with pytest.raises(ValueError):
        catalog_operator.record_review(doc["id"],"Someone",
            b"SYNTHETIC PROOF FOR UNIT TESTS WITH ENOUGH WORDS",
            "Local synthetic fixture and permissions","approve",
            confirmation="not-approved")
    assert client.get("/api/m3/imports",headers=auth).json()[0]["status"]=="pending"
