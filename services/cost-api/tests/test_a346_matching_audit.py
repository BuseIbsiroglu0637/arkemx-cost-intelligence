"""A3.46 audit cannot make an official-poz absence or cost-approval claim."""
from io import BytesIO

from openpyxl import Workbook

from app import a318_pdf_api, a346_matching_audit
from test_a318_pdf_api import positions, setup, upload
from test_api import register


def test_audit_classification_is_explicitly_uncertain():
    row = {
        "quantity": "12.50", "unit": "m²", "rejected_candidate_count": 0,
        "manual_position": None,
    }
    kind, message = a346_matching_audit.classify_missing(row, {}, {}, [])
    assert kind == "source_scope_or_description_unknown"
    assert "PDF" in message
    kind, _ = a346_matching_audit.classify_missing({**row, "quantity": None}, {}, {}, [])
    assert kind == "metraj_input_gap"
    kind, _ = a346_matching_audit.classify_missing(
        {**row, "rejected_candidate_count": 1}, {}, {}, []
    )
    assert kind == "technical_conflict"

    manually_entered = {**row, "manual_position": {
        "position_code": "15.999.1999", "current": True,
    }}
    kind, _ = a346_matching_audit.classify_missing(
        manually_entered, {"15.999.1999": 33}, {}, []
    )
    assert kind == "manual_code_in_pdf_not_parsed"
    kind, _ = a346_matching_audit.classify_missing(manually_entered, {}, {}, [])
    assert kind == "manual_code_outside_loaded_pdf"
    kind, _ = a346_matching_audit.classify_missing(
        row, {}, {}, [{"code": "15.999.1001"}],
    )
    assert kind == "possible_retrieval_gap"
    # No scan available: never pretend that a manual number is absent.
    kind, _ = a346_matching_audit.classify_missing(manually_entered, None, {}, [])
    assert kind == "source_scope_or_description_unknown"


def test_endpoint_scans_all_import_rows_without_pricing_or_approval(client, auth, monkeypatch):
    pid, iid = setup(client, auth, "A3.46 evidence")
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    monkeypatch.setattr(
        a346_matching_audit, "_raw_position_codes",
        lambda *args: {"15.999.1001": 5, "15.999.1999": 42},
    )
    source = upload(client, pid, auth)
    assert source.status_code == 201, source.text
    res = client.get(
        f"/api/projects/{pid}/a346/imports/{iid}/audit", headers=auth,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["schema"] == "arkemx.a346.matching_audit.v1"
    assert data["read_only"] is True
    assert data["approval_allowed"] is False
    assert data["cost_allowed"] is False
    assert data["source_pdf_sha256"] == source.json()["sha256"]
    assert data["total_rows"] == 2
    assert data["missing_count"] + data["candidate_count"] == 2
    assert sum(data["missing_reason_counts"].values()) == data["missing_count"]
    assert sum(data["candidate_risk_counts"].values()) == data["candidate_count"]
    assert data["source_pdf"]["codes_in_text_not_extracted_count"] == 1
    assert data["source_pdf"]["codes_in_text_not_extracted_sample"] == ["15.999.1999"]
    assert all(x["cost_allowed"] is False and x["engineer_approved"] is False
               for x in data["missing_rows"] + data["candidate_rows"])
    assert res.headers["cache-control"] == "private, no-store"


def test_all_pages_present_when_more_than_20_metraj_rows(client, auth, monkeypatch):
    project = client.post("/api/projects", headers=auth, json={"name": "A3.46 all rows"})
    assert project.status_code == 201
    pid = project.json()["id"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["İmalat", "Metraj", "Ölçü Birimi"])
    for index in range(24):
        sheet.append([
            "Gazbeton duvar uygulaması 10 cm" if index % 2 == 0
            else "Benzersiz özel PVC malzeme kodu",
            "12,50", "m2",
        ])
    buffer = BytesIO()
    workbook.save(buffer)
    saved = client.post(
        f"/api/projects/{pid}/imports", headers=auth,
        files={"file": ("audit.xlsx", buffer.getvalue())},
    )
    assert saved.status_code == 201, saved.text
    iid = saved.json()["id"]
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    monkeypatch.setattr(a346_matching_audit, "_raw_position_codes", lambda *args: {})
    assert upload(client, pid, auth).status_code == 201
    res = client.get(
        f"/api/projects/{pid}/a346/imports/{iid}/audit", headers=auth,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_rows"] == 24
    assert data["missing_count"] + data["candidate_count"] == 24
    all_source_rows = [r["source_row"] for r in data["missing_rows"] + data["candidate_rows"]]
    assert len(set(all_source_rows)) == 24


def test_audit_tenant_isolation(client, monkeypatch):
    first = register(client, "A346 owner", "a346owner@example.com")
    second = register(client, "A346 outsider", "a346outsider@example.com")
    pid, iid = setup(client, first, "Private matching audit")
    res = client.get(
        f"/api/projects/{pid}/a346/imports/{iid}/audit", headers=second,
    )
    assert res.status_code == 404
