"""A3.17 candidate proposals: source rights, no writes, isolation, multiple lines."""
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from app.database import get_db
from app.models import MatchRun

from test_api import xlsx_bytes


def login(client, org, email):
    response = client.post("/api/auth/register", json={
        "organization_name": org, "email": email, "password": "secure-pilot-password",
    })
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def setup(client, auth):
    p = client.post("/api/projects", json={"name": "A3.17 local pilot"}, headers=auth)
    assert p.status_code == 201
    pid = p.json()["id"]
    imp = client.post(f"/api/projects/{pid}/imports", headers=auth,
                      files={"file": ("metraj.xlsx", xlsx_bytes())})
    assert imp.status_code == 201, imp.text
    return pid, imp.json()["id"]


def test_suggestions_are_read_only_and_not_approval(client, auth):
    pid, iid = setup(client, auth)
    empty = client.get(f"/api/projects/{pid}/a317/catalogs", headers=auth)
    assert empty.status_code == 200
    assert empty.json()["catalogs"] == []
    seeded = client.post("/api/m2/demo-catalog", headers=auth)
    assert seeded.status_code == 201, seeded.text
    versions = client.get(f"/api/projects/{pid}/a317/catalogs", headers=auth)
    assert len(versions.json()["catalogs"]) == 1
    vid = seeded.json()["version_id"]
    result = client.get(
        f"/api/projects/{pid}/a317/imports/{iid}/suggestions",
        headers=auth, params={"version_id": vid},
    )
    assert result.status_code == 200, result.text
    doc = result.json()
    assert doc["read_only"] is True
    assert doc["approval_allowed"] is False
    assert doc["cost_allowed"] is False
    assert doc["catalog"]["synthetic"] is True
    assert doc["import_source"]["import_id"] == iid
    assert len(doc["rows"]) == 2
    assert any(r["suggestions"] for r in doc["rows"])
    assert all(c["technical_status"] in ("review", "blocked", "compatible")
               for r in doc["rows"] for c in r["suggestions"])
    assert result.headers["cache-control"] == "private, no-store"
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    assert db.scalars(select(MatchRun).where(MatchRun.project_id == pid)).all() == []
    gen.close()


def test_other_tenant_and_other_import_rejected(client):
    first = login(client, "First", "first317@example.com")
    second = login(client, "Second", "second317@example.com")
    p1, i1 = setup(client, first)
    p2, i2 = setup(client, second)
    vid = client.post("/api/m2/demo-catalog", headers=first).json()["version_id"]
    route = f"/api/projects/{p1}/a317/imports/{i1}/suggestions"
    assert client.get(route, headers=second, params={"version_id": vid}).status_code == 404
    wrong_import = f"/api/projects/{p1}/a317/imports/{i2}/suggestions"
    assert client.get(wrong_import, headers=first, params={"version_id": vid}).status_code == 404
    other_catalog = client.post("/api/m2/demo-catalog", headers=second).json()["version_id"]
    assert client.get(route, headers=first, params={"version_id": other_catalog}).status_code == 404
    assert p1 != p2


def test_suggestions_fail_closed_on_unknown_catalog(client, auth):
    pid, iid = setup(client, auth)
    response = client.get(
        f"/api/projects/{pid}/a317/imports/{iid}/suggestions", headers=auth,
        params={"version_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert response.status_code == 404


def test_repeated_poz_candidate_warns_about_double_count(client, auth):
    pid = client.post("/api/projects", json={"name": "Shared scope"}, headers=auth).json()["id"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["İmalat", "Miktar", "Birim"])
    sheet.append(["60 x 60 porselen seramik zemin kaplaması", 12, "m2"])
    sheet.append(["60 x 60 porselen seramik zemin kaplaması", 12, "m2"])
    buf = BytesIO()
    workbook.save(buf)
    imp = client.post(f"/api/projects/{pid}/imports", headers=auth,
                      files={"file": ("shared.xlsx", buf.getvalue())})
    assert imp.status_code == 201, imp.text
    vid = client.post("/api/m2/demo-catalog", headers=auth).json()["version_id"]
    response = client.get(
        f"/api/projects/{pid}/a317/imports/{imp.json()['id']}/suggestions",
        headers=auth, params={"version_id": vid},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["suggestions"][0]["code"] == rows[1]["suggestions"][0]["code"]
    assert all(row["suggestions"][0]["possible_shared_scope"] for row in rows)
