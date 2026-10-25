"""M4 engineering rule tests and end-to-end rights/approval regression."""
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy.orm import sessionmaker
from app.technical import compare, extract, VERSION
from app.m4_quality import evaluate_fixture
from app.database import get_db
from app import catalog_operator
from app.catalog_operator import CONFIRM


def auth(client, name, email):
    response=client.post("/api/auth/register",json={
        "organization_name":name,"email":email,"password":"valid-test-password-123"})
    assert response.status_code==201,response.text
    return {"Authorization":"Bearer "+response.json()["access_token"]}


def setup(client, headers):
    project=client.post("/api/projects",headers=headers,json={"name":"M4 Demo Test"})
    assert project.status_code==201,project.text
    pid=project.json()["id"]
    wb=Workbook();ws=wb.active
    ws.append(["İmalat Açıklaması","Miktar","Birim"])
    ws.append(["Porselen seramik zemin kaplama 60x60","24,5","m2"])
    wb_buf=BytesIO();wb.save(wb_buf)
    imported=client.post(f"/api/projects/{pid}/imports",headers=headers,
                          files={"file":("sample.xlsx",wb_buf.getvalue())})
    assert imported.status_code==201,imported.text
    catalog=(
       "Poz Kodu;Poz Tanımı;Birim\n"
       "DEMO-60;Porselen seramik zemin kaplama 60x60;m²\n"
       "DEMO-30;Porselen seramik zemin kaplama 30x60;m²\n"
    ).encode("utf-8-sig")
    staged=client.post("/api/m3/imports",headers=headers,
        data={"institution":"OTHER","year":"2026","period":"M4-SYNTHETIC"},
        files={"file":("technical.csv",catalog)})
    assert staged.status_code==201,staged.text
    return pid,staged.json()


def grant(client, monkeypatch, import_id):
    override=client.app.dependency_overrides[get_db]
    session=override();db=next(session)
    try:
        monkeypatch.setattr(catalog_operator,"SessionLocal",sessionmaker(bind=db.get_bind()))
    finally:
        session.close()
    catalog_operator.record_review(
        import_id,"M4 local test operator",
        b"Entirely synthetic M4 comparisons; original test fixture authored for this suite",
        "Original non-public fictional dataset for local technical testing",
        "approve",confirmation=CONFIRM
    )


def test_rule_thickness_units_and_surface():
    good=compare("Gazbeton duvar 100 mm","m²","Gazbeton duvar 10 cm","m²")
    assert good["status"]=="compatible",good
    bad=compare("Gazbeton duvar 10 cm","m²","Gazbeton duvar 15 cm","m²")
    assert bad["status"]=="blocked"
    assert "THICKNESS_MM_MISMATCH" in bad["blockers"]
    surface=compare("Porselen seramik zemin kaplama 60x60","m²",
                    "Porselen seramik duvar kaplama 60x60","m²")
    assert surface["status"]=="blocked"
    assert "SURFACE_MISMATCH" in surface["blockers"]


def test_unknown_critical_information_fails_closed():
    result=compare("Porselen seramik kaplama 60x60","m²",
                   "Porselen seramik zemin kaplama 60x60","m²")
    assert result["status"]=="review",result
    assert not result["manual_approval_allowed"]
    amount=compare("Gazbeton duvar 10 cm","m²","Gazbeton duvar 10 cm","m²",
                   quantity_known=False)
    assert amount["status"]=="blocked"
    assert "METRAJ_REVIEW_REQUIRED" in amount["blockers"]


def test_different_methods_and_materials_never_auto_approve():
    method=compare("Kapı montaj","adet","Kapı söküm","adet")
    assert "METHOD_MISMATCH" in method["blockers"]
    materials=compare("Beton döküm","m³","Çelik döküm","m³")
    assert "MATERIAL_MISMATCH" in materials["blockers"]
    assert method["manual_approval_allowed"] is False
    assert materials["manual_approval_allowed"] is False


def test_quality_fixture_no_synthetic_false_approval():
    report=evaluate_fixture()
    assert report["sample_size"] >= 12
    assert report["false_positive"] == 0,report["examples"]
    assert report["true_positive"] >= 4
    assert report["not_production_validation"]


def test_m4_end_to_end_immutable_and_gate(client,monkeypatch):
    headers=auth(client,"M4 Firm 1","m4main@example.com")
    pid,imp=setup(client,headers)
    grant(client,monkeypatch,imp["id"])
    prior=client.post(f"/api/m3/projects/{pid}/run",headers=headers,
                      json={"version_id":imp["version_id"]})
    assert prior.status_code==201,prior.text
    old=client.get(f"/api/projects/{pid}/m2/latest",headers=headers).json()
    old_c=next(c for c in old["items"][0]["candidates"] if c["code"]=="DEMO-60")
    approved=client.post(f"/api/projects/{pid}/m2/decisions",headers=headers,
                         json={"run_id":prior.json()["id"],"candidate_id":old_c["id"],
                               "action":"approve"})
    assert approved.status_code==201,approved.text

    created=client.post(f"/api/projects/{pid}/m4/run",headers=headers)
    assert created.status_code==201,created.text
    assert created.json()["parent_run_id"]==prior.json()["id"]
    assert created.json()["row_count"]==1
    assert created.json()["candidate_count"]==2
    assert created.json()["legacy_runs_unchanged"]
    latest=client.get(f"/api/projects/{pid}/m4/latest",headers=headers)
    assert latest.status_code==200,latest.text
    data=latest.json()
    assert data["run"]["algorithm"]==VERSION
    assert data["items"][0]["decision"] is None
    candidates={c["code"]:c for c in data["items"][0]["candidates"]}
    assert candidates["DEMO-60"]["technical"]["status"]=="compatible"
    assert candidates["DEMO-30"]["technical"]["status"]=="blocked"
    assert "DIMENSIONS_MISMATCH" in candidates["DEMO-30"]["technical"]["blockers"]
    assert not candidates["DEMO-30"]["approvable"]
    denied=client.post(f"/api/projects/{pid}/m2/decisions",headers=headers,
        json={"run_id":created.json()["id"],"candidate_id":candidates["DEMO-30"]["id"],
              "action":"approve"})
    assert denied.status_code==409
    accepted=client.post(f"/api/projects/{pid}/m2/decisions",headers=headers,
        json={"run_id":created.json()["id"],"candidate_id":candidates["DEMO-60"]["id"],
              "action":"approve"})
    assert accepted.status_code==201,accepted.text
    history=client.get(f"/api/projects/{pid}/m21/run-history/{prior.json()['id']}",
                       headers=headers).json()
    assert history["items"][0]["candidates"][0]["decisions"]
    assert client.post(f"/api/projects/{pid}/m21/rematch",headers=headers).status_code==409


def test_revoke_and_tenant_isolation(client,monkeypatch):
    first=auth(client,"M4 Firm A","m4a@example.com")
    other=auth(client,"M4 Firm B","m4b@example.com")
    pid,imp=setup(client,first)
    grant(client,monkeypatch,imp["id"])
    assert client.post(f"/api/m3/projects/{pid}/run",headers=first,
                       json={"version_id":imp["version_id"]}).status_code==201
    created=client.post(f"/api/projects/{pid}/m4/run",headers=first)
    assert created.status_code==201
    assert client.get(f"/api/projects/{pid}/m4/latest",headers=other).status_code==404
    assert client.post(f"/api/projects/{pid}/m4/run",headers=other).status_code==404
    catalog_operator.record_review(imp["id"],"M4 local test operator",
        b"Operator action to revoke synthetic catalog usage for security fixture",
        "Original synthetic test permission revoked","revoke")
    latest=client.get(f"/api/projects/{pid}/m4/latest",headers=first).json()
    assert not latest["run"]["rights_active"]
    assert latest["items"][0]["stale"]
    assert client.post(f"/api/projects/{pid}/m4/run",headers=first).status_code==403
    candidate=next(c for c in latest["items"][0]["candidates"] if c["code"]=="DEMO-60")
    assert client.post(f"/api/projects/{pid}/m2/decisions",headers=first,
        json={"run_id":created.json()["id"],"candidate_id":candidate["id"],
              "action":"approve"}).status_code==403
