"""A3.27: document-readiness queue is read-only and fail-closed."""
from io import BytesIO
from types import SimpleNamespace

from openpyxl import Workbook
from sqlalchemy import select

from app import a327_engineer_handoff
from app.database import get_db
from app.models import PdfCandidateSelection, User, WorkItem
from test_a326_project_evidence import attach, pdf, project_with_metraj


def readiness(client, auth, pid, iid):
    return client.get(
        f"/api/projects/{pid}/a327/imports/{iid}/readiness", headers=auth
    )


def six_row_project(client, auth):
    created = client.post(
        "/api/projects", headers=auth,
        json={"name": "A327 ornek altı imalat"},
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    wb = Workbook()
    ws = wb.active
    ws.append(["Imalat", "Miktar", "Birim"])
    for description, quantity in (
        ("10 cm gazbeton duvar imalati", 84.25),
        ("20 mm kaba siva", 100),
        ("8 mm ince siva", 100),
        ("60x60 cm porselen seramik zemin kaplamasi", 42.75),
        ("C25/30 beton imalati", 12),
        ("Ic cephe boya uygulamasi", 200),
    ):
        ws.append([description, quantity, "m²"])
    stream = BytesIO()
    wb.save(stream)
    imported = client.post(
        f"/api/projects/{pid}/imports", headers=auth,
        files={"file": ("metraj.xlsx", stream.getvalue())},
    )
    assert imported.status_code == 201, imported.text
    return pid, imported.json()["id"]


def test_handoff_covers_six_rows_and_blocks_unverified_approvals(client, auth):
    pid, iid = six_row_project(client, auth)
    uploaded = attach(client, auth, pid, pdf(
        "Gazbeton 10 cm duvar: 2,50 N/mm2 ve 400 kg/m3.\n"
        "60x60 cm porselen seramik: mat sirsiz rektifiyeli.",
    ))
    assert uploaded.status_code == 201, uploaded.text
    result = readiness(client, auth, pid, iid)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["read_only"] is True
    assert data["approval_allowed"] is False
    assert data["engineering_approved"] is False
    assert data["cost_allowed"] is False
    assert len(data["rows"]) == 6
    assert data["next_offset"] is None
    statuses = [row["status"] for row in data["rows"]]
    assert statuses.count("needs_candidate") == 2
    assert statuses.count("manual_review") == 4
    for row in data["rows"]:
        assert row["checks"]
        assert row["engineering_approved"] is False
        assert row["cost_allowed"] is False


def test_readiness_can_show_exact_saved_gazbeton_evidence_without_approval(
    client, auth, monkeypatch,
):
    pid, iid, ids = project_with_metraj(client, auth)
    assert attach(
        client, auth, pid, pdf("Gazbeton 10 cm duvar: 2,50 N/mm2 400 kg/m3")
    ).status_code == 201
    sha = "a" * 64
    monkeypatch.setattr(
        a327_engineer_handoff, "read_analysis_pdf",
        lambda user: (sha, (SimpleNamespace(
            id="15.225.1004",
            description="Gazbeton 10 cm duvar: 2,50 N/mm2 400 kg/m3",
        ),)),
    )
    gen = client.app.dependency_overrides[get_db]()
    session = next(gen)
    owner = session.scalar(select(User))
    session.add(PdfCandidateSelection(
        organization_id=owner.organization_id, project_id=pid,
        import_id=iid, work_item_id=ids[0],
        selected_by_id=owner.id, revision_id=None,
        pdf_sha256=sha, position_code="15.225.1004",
    ))
    session.commit()
    gen.close()
    response = readiness(client, auth, pid, iid)
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert rows[0]["status"] == "documented_for_review", rows[0]
    assert rows[0]["saved_candidate"] == "15.225.1004"
    assert rows[0]["evidence_page"] == 1
    assert rows[0]["engineering_approved"] is False
    assert rows[0]["cost_allowed"] is False
    assert rows[1]["status"] == "needs_document"

    monkeypatch.setattr(
        a327_engineer_handoff, "read_analysis_pdf",
        lambda user: ("b" * 64, ()),
    )
    stale = readiness(client, auth, pid, iid).json()
    assert stale["rows"][0]["status"] == "stale_candidate"
    assert stale["rows"][0]["engineering_approved"] is False


def test_readiness_is_tenant_scoped_and_does_not_require_document(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    own = readiness(client, auth, pid, iid)
    assert own.status_code == 200
    assert own.json()["document_state"] == "missing"
    assert all(r["status"] == "needs_document" for r in own.json()["rows"])
    registration = client.post("/api/auth/register", json={
        "organization_name": "Other firm",
        "email": "a327-other@example.com",
        "password": "secure-pilot-password",
    })
    assert registration.status_code == 201
    other = {"Authorization": "Bearer " + registration.json()["access_token"]}
    assert readiness(client, other, pid, iid).status_code == 404
