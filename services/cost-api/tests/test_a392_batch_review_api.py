"""Authorization, source selection, revision and non-persistence API tests."""

from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import event

from app.database import get_db
from app.models import MetrajImportExclusion
from app.technical_analysis import batch_technical_review as pilot

TEXT = (
    "250 kg çimento dozlu 20 mm kaba sıva üzerine 350 kg çimento dozlu 8 mm ince sıva"
)


def imported(client, headers, count=3):
    project = client.post("/api/projects", headers=headers, json={"name": "A392 Pilot"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    book = Workbook()
    sheet = book.active
    sheet.title = "Metraj"
    sheet.append(["İmalat Açıklaması", "Miktar", "Birim"])
    for _ in range(count):
        sheet.append([TEXT, 10, "m2"])
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    response = client.post(
        f"/api/projects/{pid}/imports",
        headers=headers,
        files={"file": ("pilot.xlsx", buffer.getvalue())},
    )
    assert response.status_code == 201, response.text
    iid = response.json()["id"]
    base = f"/api/projects/{pid}/a3/imports/{iid}"
    listed = client.get(base + "/items", headers=headers)
    assert listed.status_code == 200, listed.text
    return pid, iid, base, listed.json()["rows"]


def selection(row, **changes):
    result = {
        "work_item_id": row["work_item_id"],
        "candidate_code": "15.275.1111",
        "expected_revision_id": row["revision_id"],
    }
    return {**result, **changes}


@pytest.fixture
def verified_source(monkeypatch):
    monkeypatch.setenv("ARKEMX_ANALYSIS_PDF", "synthetic-test-source.pdf")
    monkeypatch.setattr(
        pilot,
        "read_analysis",
        lambda _path: {
            "position_code": "15.275.1111",
            "unit": "m²",
            "read_only": True,
            "approval_allowed": False,
            "technical_description": {"quote": TEXT},
            "totals": {"total": "744.50", "currency": "TRY"},
            "source": {"sha256": "synthetic-test-source", "pdf_page": 423},
        },
    )


def test_both_routes_require_authentication(client):
    base = f"/api/projects/{uuid4()}/a3/imports/{uuid4()}"
    assert client.get(base + "/items").status_code == 401
    assert (
        client.post(
            base + "/technical-review",
            json={
                "rows": [
                    {"work_item_id": str(uuid4())},
                ]
            },
        ).status_code
        == 401
    )


def test_selected_rows_preserve_order_and_excel_identity(client, auth, verified_source):
    _pid, iid, base, rows = imported(client, auth)
    response = client.post(
        base + "/technical-review",
        headers=auth,
        json={"rows": [selection(rows[2]), selection(rows[0])]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["row_count"] == 2
    assert [r["identity"]["work_item_id"] for r in data["rows"]] == [
        rows[2]["work_item_id"],
        rows[0]["work_item_id"],
    ]
    assert [r["identity"]["source_row"] for r in data["rows"]] == [4, 2]
    assert all(r["identity"]["import_id"] == iid for r in data["rows"])
    assert all(r["technical_status"] == "checked_features_match" for r in data["rows"])
    assert all(r["approval_allowed"] is False for r in data["rows"])
    assert response.headers["cache-control"] == "private, no-store"
    assert data["import_source"]["sheet_name"] == "Metraj"
    assert len(data["import_source"]["sha256"]) == 64


def test_pagination_does_not_mix_or_drop_rows(client, auth):
    _pid, _iid, base, rows = imported(client, auth)
    first = client.get(base + "/items?limit=2", headers=auth).json()
    second = client.get(base + "/items?limit=2&offset=2", headers=auth).json()
    assert first["next_offset"] == 2
    assert second["next_offset"] is None
    assert first["rows"] + second["rows"] == rows


def test_other_organization_cannot_read_or_review(client, auth):
    _pid, _iid, base, rows = imported(client, auth)
    response = client.post(
        "/api/auth/register",
        json={
            "organization_name": "Other Office",
            "email": "other-a392@example.com",
            "password": "secure-other-a392-password",
        },
    )
    other = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get(base + "/items", headers=other).status_code == 404
    assert (
        client.post(
            base + "/technical-review",
            headers=other,
            json={"rows": [selection(rows[0])]},
        ).status_code
        == 404
    )


def test_foreign_import_and_foreign_row_are_rejected(client, auth):
    pid, _iid, base, rows = imported(client, auth)
    _other_pid, other_iid, _other_base, other_rows = imported(client, auth)
    wrong_base = f"/api/projects/{pid}/a3/imports/{other_iid}"
    assert client.get(wrong_base + "/items", headers=auth).status_code == 404
    response = client.post(
        base + "/technical-review",
        headers=auth,
        json={"rows": [selection(rows[0]), selection(other_rows[0])]},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "kind", ["empty", "too_many", "duplicate", "client_path", "client_text"]
)
def test_invalid_or_client_supplied_sources_are_rejected(client, auth, kind):
    _pid, _iid, base, rows = imported(client, auth)
    payload = {"rows": [selection(rows[0])]}
    if kind == "empty":
        payload["rows"] = []
    elif kind == "too_many":
        payload["rows"] = [{"work_item_id": str(uuid4())} for _ in range(21)]
    elif kind == "duplicate":
        payload["rows"] *= 2
    elif kind == "client_path":
        payload["pdf_path"] = "C:/untrusted.pdf"
    else:
        payload["rows"][0]["description"] = "Client override"
    assert (
        client.post(base + "/technical-review", headers=auth, json=payload).status_code
        == 422
    )


def test_revision_changes_require_reload_then_use_effective_text(
    client, auth, verified_source
):
    pid, _iid, base, rows = imported(client, auth)
    old_selection = selection(rows[0])
    revised = TEXT.replace("8 mm", "5 mm")
    response = client.post(
        f"/api/projects/{pid}/m21/items/{rows[0]['work_item_id']}/revisions",
        headers=auth,
        json={
            "description": revised,
            "quantity": "10",
            "unit": "m2",
            "reason": "A392 synthetic correction",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 201, response.text
    assert (
        client.post(
            base + "/technical-review", headers=auth, json={"rows": [old_selection]}
        ).status_code
        == 409
    )
    latest = client.get(base + "/items", headers=auth).json()["rows"][0]
    result = client.post(
        base + "/technical-review", headers=auth, json={"rows": [selection(latest)]}
    )
    assert result.status_code == 200, result.text
    row = result.json()["rows"][0]
    assert row["original_description"] == TEXT
    assert row["effective_description"] == revised
    assert row["identity"]["revision_id"] == latest["revision_id"]
    assert row["technical_status"] == "incompatible"


def test_excluded_import_cannot_be_used(client, auth):
    pid, iid, base, rows = imported(client, auth)
    actor = client.get("/api/me", headers=auth).json()
    source = client.get(base + "/items", headers=auth).json()["import_source"]
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.add(
            MetrajImportExclusion(
                import_id=iid,
                organization_id=actor["organization_id"],
                project_id=pid,
                original_sha256=source["sha256"],
                reason="Synthetic exclusion for A392",
                excluded_by_id=actor["id"],
            )
        )
        db.commit()
    finally:
        generator.close()
    assert client.get(base + "/items", headers=auth).status_code == 409
    assert (
        client.post(
            base + "/technical-review",
            headers=auth,
            json={"rows": [selection(rows[0])]},
        ).status_code
        == 409
    )


def test_source_not_configured_is_explicit_per_row(client, auth, monkeypatch):
    _pid, _iid, base, rows = imported(client, auth)
    monkeypatch.delenv("ARKEMX_ANALYSIS_PDF", raising=False)
    response = client.post(
        base + "/technical-review", headers=auth, json={"rows": [selection(rows[0])]}
    )
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["price_source_status"] == "not_configured"
    assert row["technical_status"] == "review_required"
    assert row["source_price"] is None


def test_preview_routes_execute_no_database_writes(client, auth, verified_source):
    _pid, _iid, base, rows = imported(client, auth)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    engine = db.get_bind()
    generator.close()
    writes = []

    def record_write(_conn, _cursor, statement, _parameters, _context, _many):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
        ):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record_write)
    try:
        assert client.get(base + "/items", headers=auth).status_code == 200
        response = client.post(
            base + "/technical-review",
            headers=auth,
            json={"rows": [selection(rows[0])]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["read_only"] is True
        assert response.json()["approval_allowed"] is False
    finally:
        event.remove(engine, "before_cursor_execute", record_write)
    assert writes == []
