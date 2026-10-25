"""M4.1 evidence schema, falsification, tenant isolation and rights gate regression."""
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from app.evidence_v41 import analyze, extract_evidence, verify_evidence, ALGORITHM
from app.models import TechnicalEvidence
from app.database import get_db
from app import catalog_operator
from app.catalog_operator import CONFIRM


def auth(client, name, email):
    resp = client.post("/api/auth/register", json={
        "organization_name": name, "email": email, "password": "m41-secure-demo-password"})
    assert resp.status_code == 201, resp.text
    return {"Authorization": "Bearer " + resp.json()["access_token"]}


def project_and_catalog(client, headers):
    resp = client.post("/api/projects", headers=headers, json={"name": "M4.1 Evidence Pilot"})
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    wb = Workbook(); sheet = wb.active
    sheet.append(["İmalat Açıklaması", "Miktar", "Birim"])
    sheet.append(["Hazır beton döküm C25/30 nakliye dahildir", "12,5", "m3"])
    f = BytesIO(); wb.save(f)
    imported = client.post(f"/api/projects/{pid}/imports", headers=headers,
        files={"file": ("test.xlsx", f.getvalue())})
    assert imported.status_code == 201, imported.text
    csv = ("Poz Kodu;Poz Tanımı;Birim\n"
           "DEMO-C25;Hazır beton döküm C25/30 nakliye dahildir;m³\n"
           "DEMO-C30;Hazır beton döküm C30/37 nakliye dahildir;m³\n"
           "DEMO-NO;Hazır beton döküm C25/30 nakliye hariç;m³\n").encode("utf-8-sig")
    staged = client.post("/api/m3/imports", headers=headers,
        data={"institution": "OTHER", "year": "2026", "period": "M41-FIXTURE"},
        files={"file": ("catalog.csv", csv)})
    assert staged.status_code == 201, staged.text
    return pid, staged.json()


def grant(client, monkeypatch, import_id):
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    monkeypatch.setattr(catalog_operator, "SessionLocal", sessionmaker(bind=db.get_bind()))
    gen.close()
    catalog_operator.record_review(
        import_id, "M41 test operator",
        b"Entirely synthetic engineering evidence test data authored in this suite",
        "Original synthetic engineering fixture with locally reviewed test rights",
        "approve", confirmation=CONFIRM)


def test_concrete_class_critical_mismatch():
    result = analyze("Hazır beton döküm C25/30 nakliye dahildir", "m³",
                     "Hazır beton döküm C30/37 nakliye dahildir", "m³")
    assert result["status"] == "blocked"
    assert "CONCRETE_CLASS_MISMATCH" in result["blockers"]
    assert not result["approval_allowed"]
    assert verify_evidence(result)
    cls = next(v for v in result["checks"] if v["key"] == "concrete_class")
    assert cls["metraj"]["value"] == "C25/30"
    assert cls["catalog"]["value"] == "C30/37"


def test_scope_included_excluded_and_missing_information():
    result = analyze("Hazır beton döküm C25/30 nakliye dahildir", "m³",
                     "Hazır beton döküm C25/30 nakliye hariç", "m³")
    assert result["status"] == "blocked"
    assert "SCOPE_NAKLIYE_MISMATCH" in result["blockers"]
    missing = analyze("Hazır beton döküm C25/30", "m³",
                      "Hazır beton döküm C25/30 nakliye dahildir", "m³")
    assert missing["status"] == "review"
    assert "SCOPE_NAKLIYE_UNVERIFIED" in missing["review_flags"]
    assert not missing["approval_allowed"]
    simple = analyze("Hazır beton döküm C25/30", "m³",
                     "Hazır beton döküm C25/30", "m³")
    assert "SCOPE_NOT_VERIFIABLE_FROM_TITLES" in simple["review_flags"]


def test_standard_and_ambiguous_concrete_class():
    diff = analyze("Beton döküm C25/30 TS EN 206 nakliye dahil", "m³",
                   "Beton döküm C25/30 TS EN 197-1 nakliye dahil", "m³")
    assert "STANDARD_MISMATCH" in diff["blockers"]
    ambiguous = analyze("Beton C25/30 C30/37 nakliye dahil", "m³",
                        "Beton C25/30 nakliye dahil", "m³")
    assert "CONCRETE_CLASS_AMBIGUOUS" in ambiguous["review_flags"]
    assert not ambiguous["approval_allowed"]


def test_evidence_spans_hash_and_noninvented_quotes():
    output = analyze("Hazır beton C25/30 nakliye dahildir", "m³",
                     "Hazır beton C25/30 nakliye dahildir", "m³")
    check = next(v for v in output["checks"] if v["key"] == "concrete_class")
    normalized = output["sources"]["metraj"]["normalized_text"]
    ref = check["metraj"]["quote"]
    assert normalized[ref["start"]:ref["end"]] == ref["excerpt"]
    assert ref["offset_basis"] == "normalized_text"
    assert len(output["sources"]["metraj"]["sha256"]) == 64
    assert verify_evidence(output)
    output["checks"][0]["status"] = "block"
    assert not verify_evidence(output)


def test_m41_run_preserves_old_m4_and_protects_decisions(client, monkeypatch):
    headers = auth(client, "M41 Firm A", "m41a@example.com")
    pid, staged = project_and_catalog(client, headers)
    grant(client, monkeypatch, staged["id"])
    m3 = client.post(f"/api/m3/projects/{pid}/run", headers=headers,
         json={"version_id": staged["version_id"]})
    assert m3.status_code == 201, m3.text
    m4 = client.post(f"/api/projects/{pid}/m4/run", headers=headers)
    assert m4.status_code == 201, m4.text
    m41 = client.post(f"/api/projects/{pid}/m41/run", headers=headers)
    assert m41.status_code == 201, m41.text
    assert m41.json()["algorithm"] == ALGORITHM
    assert m41.json()["parent_run_id"] == m4.json()["id"]
    assert m41.json()["candidate_count"] == 3
    assert m41.json()["technical_statuses"]["blocked"] >= 2
    res = client.get(f"/api/projects/{pid}/m41/latest", headers=headers)
    assert res.status_code == 200, res.text
    record = res.json()
    assert record["run"]["algorithm"] == ALGORITHM
    cands = {v["code"]: v for v in record["items"][0]["candidates"]}
    assert cands["DEMO-C25"]["evidence"]["status"] == "compatible"
    assert cands["DEMO-C30"]["evidence"]["status"] == "blocked"
    assert cands["DEMO-NO"]["evidence"]["status"] == "blocked"
    assert cands["DEMO-C25"]["evidence"]["source_refs"]["catalog"]["version_sha256"] == staged["sha256"]
    assert all(v["evidence"]["evidence_sha256"] for v in cands.values())
    assert record["items"][0]["decision"] is None
    invalid = client.post(f"/api/projects/{pid}/m2/decisions", headers=headers,
         json={"run_id": m41.json()["id"], "candidate_id": cands["DEMO-C30"]["id"],
               "action": "approve"})
    assert invalid.status_code == 409
    allowed = client.post(f"/api/projects/{pid}/m2/decisions", headers=headers,
         json={"run_id": m41.json()["id"], "candidate_id": cands["DEMO-C25"]["id"],
               "action": "approve"})
    assert allowed.status_code == 201, allowed.text
    old_runs = client.get(f"/api/projects/{pid}/m21/run-history", headers=headers)
    assert old_runs.status_code == 200
    assert len(old_runs.json()) == 3
    assert client.post(f"/api/projects/{pid}/m21/rematch", headers=headers).status_code == 409

    # Corrupted evidence is rejected independently of candidate.approvable.
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    row = db.scalar(select(TechnicalEvidence).where(
        TechnicalEvidence.candidate_id == cands["DEMO-C25"]["id"]))
    row.evidence_sha256 = "0" * 64
    db.commit()
    gen.close()
    badread = client.get(f"/api/projects/{pid}/m41/latest", headers=headers)
    assert badread.status_code == 409
    denied = client.post(f"/api/projects/{pid}/m2/decisions", headers=headers,
        json={"run_id": m41.json()["id"], "candidate_id": cands["DEMO-C25"]["id"],
              "action": "approve"})
    assert denied.status_code == 409


def test_m41_tenant_isolation_and_revocation(client, monkeypatch):
    a = auth(client, "M41 Owner", "m41owner@example.com")
    b = auth(client, "M41 Stranger", "m41stranger@example.com")
    pid, staged = project_and_catalog(client, a)
    grant(client, monkeypatch, staged["id"])
    assert client.post(f"/api/m3/projects/{pid}/run", headers=a,
                       json={"version_id": staged["version_id"]}).status_code == 201
    run = client.post(f"/api/projects/{pid}/m41/run", headers=a)
    assert run.status_code == 201
    assert client.get(f"/api/projects/{pid}/m41/latest", headers=b).status_code == 404
    assert client.post(f"/api/projects/{pid}/m41/run", headers=b).status_code == 404
    catalog_operator.record_review(
        staged["id"], "M41 test operator",
        b"Original synthetic test catalog deliberately revoked for this fixture",
        "Rights revoked after run for access-control regression", "revoke")
    prior = client.get(f"/api/projects/{pid}/m41/latest", headers=a).json()
    assert prior["run"]["rights_active"] is False
    assert prior["items"][0]["stale"]
    assert client.post(f"/api/projects/{pid}/m41/run", headers=a).status_code == 403
    good = next(c for c in prior["items"][0]["candidates"] if c["code"] == "DEMO-C25")
    blocked = client.post(f"/api/projects/{pid}/m2/decisions", headers=a,
        json={"run_id": run.json()["id"], "candidate_id": good["id"], "action": "approve"})
    assert blocked.status_code == 403


def test_qualifier_for_adjacent_scope_item_is_not_attributed_to_first():
    evidence = analyze(
        "Hazır beton döküm C25/30 nakliye işçilik dahildir", "m³",
        "Hazır beton döküm C25/30 nakliye işçilik dahildir", "m³")
    scope_nakliye = next(c for c in evidence["checks"] if c["key"] == "scope_nakliye")
    scope_iscilik = next(c for c in evidence["checks"] if c["key"] == "scope_iscilik")
    assert scope_nakliye["status"] == "review"
    assert scope_iscilik["status"] == "match"
    assert "SCOPE_NAKLIYE_AMBIGUOUS" in evidence["review_flags"]
    assert evidence["approval_allowed"] is False
