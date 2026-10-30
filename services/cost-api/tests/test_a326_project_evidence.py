"""A3.26 project technical-spec upload and page-cited evidence tests."""
from io import BytesIO

import pymupdf
from openpyxl import Workbook

from app.a326_project_evidence import _block_matches, _evidence_status


def pdf(*pages: str) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((50, 90), text, fontsize=11)
    result = document.tobytes()
    document.close()
    return result


def project_with_metraj(client, auth):
    p = client.post("/api/projects", headers=auth, json={"name": "A326 Proje Sartnamesi"})
    assert p.status_code == 201, p.text
    project_id = p.json()["id"]
    wb = Workbook()
    sheet = wb.active
    sheet.append(["Imalat", "Miktar", "Birim"])
    sheet.append(["10 cm gazbeton duvar imalati", 84.25, "m²"])
    sheet.append(["60x60 cm porselen seramik zemin kaplamasi", 42.75, "m²"])
    stream = BytesIO()
    wb.save(stream)
    imported = client.post(
        f"/api/projects/{project_id}/imports", headers=auth,
        files={"file": ("metraj.xlsx", stream.getvalue())},
    )
    assert imported.status_code == 201, imported.text
    iid = imported.json()["id"]
    from app.database import get_db
    from app.models import WorkItem
    from sqlalchemy import select

    gen = client.app.dependency_overrides[get_db]()
    session = next(gen)
    items = session.scalars(
        select(WorkItem).where(WorkItem.import_id == iid).order_by(WorkItem.source_row)
    ).all()
    ids = [row.id for row in items]
    gen.close()
    return project_id, iid, ids


def attach(client, auth, pid, raw):
    return client.post(
        f"/api/projects/{pid}/a326/source", headers=auth,
        files={"file": ("teknik-sartname.pdf", raw, "application/pdf")},
    )


def evidence(client, auth, pid, iid, item):
    return client.get(
        f"/api/projects/{pid}/a326/imports/{iid}/items/{item}/evidence",
        headers=auth,
    )


def test_missing_document_reports_no_document_and_no_approval(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    result = evidence(client, auth, pid, iid, ids[0])
    assert result.status_code == 200, result.text
    assert result.json() == {
        "status": "no_document", "evidence": [],
        "engineering_approved": False, "cost_allowed": False,
    }


def test_gazbeton_facts_include_exact_page_and_source_sha(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    raw = pdf(
        "Baslik: genel sartlar",
        "Gazbeton 10 cm duvar: 2,50 N/mm2 dayanim ve 400 kg/m3 yogunluk.",
    )
    attached = attach(client, auth, pid, raw)
    assert attached.status_code == 201, attached.text
    assert attached.json()["page_count"] == 2
    data = evidence(client, auth, pid, iid, ids[0]).json()
    assert data["status"] == "found_for_review", data
    assert data["source_sha256"] == attached.json()["sha256"]
    assert data["evidence"][0]["page"] == 2
    assert data["evidence"][0]["facts"]["gazbeton_strength_n_mm2"] == 2.5
    assert data["evidence"][0]["facts"]["gazbeton_density_kg_m3"] == 400
    assert data["engineering_approved"] is False
    assert data["cost_allowed"] is False


def test_conflicting_strength_values_are_not_silently_resolved(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    raw = pdf(
        "Gazbeton 10 cm duvar: 2,50 N/mm2 ve 400 kg/m3.",
        "Gazbeton 10 cm duvar: 3,50 N/mm2 ve 500 kg/m3.",
    )
    assert attach(client, auth, pid, raw).status_code == 201
    result = evidence(client, auth, pid, iid, ids[0]).json()
    assert result["status"] == "conflicting"
    assert result["engineering_approved"] is False
    assert len(result["evidence"]) == 2


def test_ceramic_finish_evidence_is_source_linked_without_approval(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    assert attach(client, auth, pid, pdf(
        "60x60 cm porselen seramik karo: mat sirsiz rektifiyeli."
    )).status_code == 201
    result = evidence(client, auth, pid, iid, ids[1]).json()
    assert result["status"] == "found_for_review", result
    assert result["evidence"][0]["facts"]["glaze"] == "sirsiz"
    assert result["evidence"][0]["facts"]["surface"] == "mat"
    assert result["cost_allowed"] is False


def test_no_matching_project_fact_stays_missing(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    assert attach(client, auth, pid, pdf("Sadece genel proje basligi")).status_code == 201
    result = evidence(client, auth, pid, iid, ids[0]).json()
    assert result["status"] == "not_found"
    assert result["evidence"] == []


def test_rejects_invalid_file_without_overwriting_existing_document(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    attached = attach(client, auth, pid, pdf("Gazbeton 10 cm duvar 2,50 N/mm2"))
    old_sha = attached.json()["sha256"]
    bad = attach(client, auth, pid, b"%PDF-broken")
    assert bad.status_code == 422
    status = client.get(f"/api/projects/{pid}/a326/source", headers=auth)
    assert status.status_code == 200
    assert status.json()["sha256"] == old_sha


def test_cross_tenant_cannot_read_or_replace_project_document(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    assert attach(client, auth, pid, pdf("Gazbeton 10 cm 2,50 N/mm2")).status_code == 201
    user = client.post("/api/auth/register", json={
        "organization_name": "Unrelated Organization",
        "email": "a326-other@example.com",
        "password": "secure-pilot-password",
    })
    assert user.status_code == 201, user.text
    other = {"Authorization": "Bearer " + user.json()["access_token"]}
    assert client.get(f"/api/projects/{pid}/a326/source", headers=other).status_code == 404
    assert attach(client, other, pid, pdf("Gazbeton 10 cm 5,00 N/mm2")).status_code == 404
    assert evidence(client, other, pid, iid, ids[0]).status_code == 404


def test_wrong_row_is_not_accessible_across_import(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    other_project, other_import, other_ids = project_with_metraj(client, auth)
    assert attach(client, auth, pid, pdf("Gazbeton 10 cm 2,50 N/mm2")).status_code == 201
    assert evidence(client, auth, pid, iid, other_ids[0]).status_code == 404


def test_metadata_only_never_approves(candidate_code=None):
    found = _block_matches(
        "10 cm gazbeton duvar",
        [(1, "Gazbeton 10 cm 2,50 N/mm2 400 kg/m3")],
    )
    assert _evidence_status(found) == "found_for_review"
