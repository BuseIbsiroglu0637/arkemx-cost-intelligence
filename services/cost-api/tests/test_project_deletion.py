"""Project hard-delete API: exact confirmation, isolation, source cleanup."""
from pathlib import Path

from app.database import get_db
from app.models import Project, WorkItem, ImportBatch
from sqlalchemy import select

from tests.test_api import xlsx_bytes


def make_project(client, headers, name):
    response = client.post("/api/projects", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_delete_empty_project_requires_exact_confirmation(client, auth):
    one = make_project(client, auth, "To be removed")
    other = make_project(client, auth, "Keep this one")
    target = f"/api/projects/{one}"
    assert client.request("DELETE", target, json={
        "confirm_project_id": one, "confirm_name": "Wrong name"
    }, headers=auth).status_code == 409
    assert client.request("DELETE", target, json={
        "confirm_project_id": other, "confirm_name": "To be removed"
    }, headers=auth).status_code == 409
    assert client.request("DELETE", target, json={
        "confirm_project_id": one, "confirm_name": "To be removed"
    }).status_code == 401
    deleted = client.request("DELETE", target, json={
        "confirm_project_id": one, "confirm_name": "To be removed"
    }, headers=auth)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_project_id"] == one
    names = [row["name"] for row in client.get("/api/projects", headers=auth).json()]
    assert names == ["Keep this one"]
    assert client.request("DELETE", target, json={
        "confirm_project_id": one, "confirm_name": "To be removed"
    }, headers=auth).status_code == 404


def test_delete_project_with_metraj_keeps_other_project(client, auth, tmp_path):
    first = make_project(client, auth, "Delete imports")
    second = make_project(client, auth, "Keep imports")
    for pid in (first, second):
        upload = client.post(
            f"/api/projects/{pid}/imports",
            files={"file": ("metraj.xlsx", xlsx_bytes())},
            headers=auth,
        )
        assert upload.status_code == 201, upload.text
    deleted = client.request("DELETE", f"/api/projects/{first}", json={
        "confirm_project_id": first, "confirm_name": "Delete imports"
    }, headers=auth)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_import_count"] == 1
    assert deleted.json()["cleanup_pending"] is False
    assert client.get(f"/api/projects/{first}/items", headers=auth).status_code == 404
    assert len(client.get(f"/api/projects/{second}/items", headers=auth).json()) == 2
    assert not list((tmp_path / "uploads").glob(f"*/{first}/*.xlsx"))
    assert len(list((tmp_path / "uploads").glob(f"*/{second}/*.xlsx"))) == 1
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    assert db.scalar(select(Project).where(Project.id == first)) is None
    assert db.scalars(select(ImportBatch).where(ImportBatch.project_id == first)).all() == []
    assert db.scalars(
        select(WorkItem).join(ImportBatch, WorkItem.import_id == ImportBatch.id)
        .where(ImportBatch.project_id == first)
    ).all() == []
    gen.close()


def test_cross_tenant_cannot_delete_project(client):
    first = client.post("/api/auth/register", json={
        "organization_name": "Tenant One", "email": "deleteone@example.com",
        "password": "secure-pilot-password"
    }).json()["access_token"]
    second = client.post("/api/auth/register", json={
        "organization_name": "Tenant Two", "email": "deletetwo@example.com",
        "password": "secure-pilot-password"
    }).json()["access_token"]
    h1 = {"Authorization": f"Bearer {first}"}
    h2 = {"Authorization": f"Bearer {second}"}
    pid = make_project(client, h1, "Private project")
    result = client.request("DELETE", f"/api/projects/{pid}", json={
        "confirm_project_id": pid, "confirm_name": "Private project"
    }, headers=h2)
    assert result.status_code == 404
    assert client.get("/api/projects", headers=h1).json()[0]["id"] == pid
