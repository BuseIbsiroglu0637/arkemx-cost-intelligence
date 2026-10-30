"""A3.21 persistent choices: save/refresh/switch, tenant isolation and source safety."""
from decimal import Decimal

from sqlalchemy import select

from app import a318_pdf_api
from app.database import get_db
from app.models import User, WorkItem, WorkItemRevision
from test_a318_pdf_api import positions, setup, upload


def _source_and_row(client, auth, monkeypatch):
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    pid, iid = setup(client, auth)
    attached = upload(client, pid, auth)
    assert attached.status_code == 201, attached.text
    path = f"/api/projects/{pid}/a318/imports/{iid}"
    result = client.get(f"{path}/suggestions", headers=auth)
    assert result.status_code == 200
    item = result.json()["rows"][0]
    return path, item, attached.json()["sha256"]


def _pick(client, auth, path, item, sha, code="15.999.1001"):
    return client.post(
        f"{path}/items/{item['work_item_id']}/candidate",
        headers=auth,
        json={"position_code": code,
              "expected_pdf_sha256": sha,
              "expected_revision_id": item["revision_id"]},
    )


def test_saved_choice_survives_new_get_and_may_be_replaced(client, auth, monkeypatch):
    path, item, sha = _source_and_row(client, auth, monkeypatch)
    saved = _pick(client, auth, path, item, sha)
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] is True
    assert saved.json()["engineering_approved"] is False
    assert saved.json()["cost_allowed"] is False
    current = client.get(f"{path}/suggestions", headers=auth)
    choice = current.json()["rows"][0]["saved_selection"]
    assert choice["current"] is True
    assert choice["code"] == "15.999.1001"
    # Change the selection to another actual code in exactly the same PDF.
    swapped = _pick(client, auth, path, item, sha, "15.999.1002")
    assert swapped.status_code == 200, swapped.text
    refreshed = client.get(f"{path}/suggestions", headers=auth).json()
    assert refreshed["rows"][0]["saved_selection"]["code"] == "15.999.1002"
    assert refreshed["approval_allowed"] is False
    assert refreshed["cost_allowed"] is False


def test_rejects_unlisted_code_and_changed_pdf_sha(client, auth, monkeypatch):
    path, item, sha = _source_and_row(client, auth, monkeypatch)
    assert _pick(client, auth, path, item, sha, "15.999.9999").status_code == 422
    assert _pick(client, auth, path, item, "0" * 64).status_code == 409
    assert client.get(f"{path}/suggestions", headers=auth).json()["rows"][0]["saved_selection"] is None


def test_stale_metraj_revision_never_restores_as_current(client, auth, monkeypatch):
    path, item, sha = _source_and_row(client, auth, monkeypatch)
    assert _pick(client, auth, path, item, sha).status_code == 200
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    source = db.scalar(select(WorkItem).where(WorkItem.id == item["work_item_id"]))
    author = db.scalar(select(User).where(User.email == "demo@example.com"))
    db.add(WorkItemRevision(
        work_item_id=source.id, revision=1,
        description=source.raw_description + " 500 kg/m³",
        quantity=Decimal(str(source.quantity)), unit=source.normalized_unit,
        corrected_by_id=author.id, reason="Revizyon testi",
    ))
    db.commit()
    gen.close()
    refreshed = client.get(f"{path}/suggestions", headers=auth).json()
    choice = refreshed["rows"][0]["saved_selection"]
    assert choice["stale"] is True
    assert choice["current"] is False
    assert choice["code"] is None
    assert _pick(client, auth, path, item, sha).status_code == 409


def test_changed_pdf_source_does_not_restore_old_choice(client, auth, monkeypatch):
    path, item, sha = _source_and_row(client, auth, monkeypatch)
    assert _pick(client, auth, path, item, sha).status_code == 200
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    author = db.scalar(select(User).where(User.email == "demo@example.com"))
    source_path = a318_pdf_api._path(author)
    gen.close()
    source_path.write_bytes(b"%PDF-" + b"Z" * 1600)
    refreshed = client.get(f"{path}/suggestions", headers=auth).json()
    assert refreshed["rows"][0]["saved_selection"]["stale"] is True
    assert refreshed["rows"][0]["saved_selection"]["code"] is None
    assert _pick(client, auth, path, item, sha).status_code == 409


def test_cross_tenant_cannot_save_other_project_choice(client, auth, monkeypatch):
    path, item, sha = _source_and_row(client, auth, monkeypatch)
    other = client.post("/api/auth/register", json={
        "organization_name": "Second A321 Organization",
        "email": "second-a321@example.com",
        "password": "secure-pilot-password",
    })
    assert other.status_code == 201
    other_auth = {"Authorization": "Bearer " + other.json()["access_token"]}
    assert _pick(client, other_auth, path, item, sha).status_code == 404
    assert client.get(f"{path}/suggestions", headers=other_auth).status_code == 404
    assert client.get(f"{path}/suggestions", headers=auth).json()["rows"][0]["saved_selection"] is None
