"""Isolation, integrity, idempotency and freshness of saved previews."""
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_a392_batch_review_api import TEXT, imported, selection
from test_m41 import auth as make_auth

from app import a3_review_records as records
from app.a3_review_records import digest
from app.a3_review_store import TechnicalReviewRecord
from app.database import get_db
from app.models import MetrajImportExclusion, User
from app.technical_analysis import batch_technical_review as pilot


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"synthetic PDF fixture")
    monkeypatch.setenv("ARKEMX_ANALYSIS_PDF", str(path))
    def read(_path):
        return {"position_code": "15.275.1111", "unit": "m²", "read_only": True,
                "approval_allowed": False, "technical_description": {"quote": TEXT},
                "totals": {"total": "744.50", "currency": "TRY"},
                "source": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "pdf_page": 423, "printed_page": 418, "filename": path.name,
                           "price_date": "2026-01-01"}}
    monkeypatch.setattr(pilot, "read_analysis", read)
    return path


def prepared(client, auth):
    pid, iid, base, rows = imported(client, auth)
    chosen = [selection(rows[0]), selection(rows[1], candidate_code=None)]
    preview = client.post(base + "/technical-review", headers=auth, json={"rows": chosen})
    assert preview.status_code == 200, preview.text
    body = {"title": "Synthetic review", "rows": chosen, "request_key": str(uuid4()),
            "expected_report_sha256": digest(preview.json())}
    return pid, iid, base, rows, body


def saved(client, auth):
    data = prepared(client, auth)
    response = client.post(data[2] + "/reviews", headers=auth, json=data[4])
    assert response.status_code == 201, response.text
    return data, response.json()


def get_record(client, auth, pid, record):
    return client.get(f"/api/projects/{pid}/a3/reviews/{record['record']['id']}", headers=auth)


def revise(client, auth, pid, row):
    response = client.post(f"/api/projects/{pid}/m21/items/{row['work_item_id']}/revisions", headers=auth,
        json={"description": TEXT.replace("8 mm", "5 mm"), "quantity": "10", "unit": "m2",
              "reason": "Synthetic independent correction", "expected_revision": 0})
    assert response.status_code == 201, response.text


def test_reopen_and_retry_are_immutable_and_never_approve(client, auth, source):
    (pid, _iid, base, _rows, body), record = saved(client, auth)
    assert record["currentness"]["status"] == "unchanged"
    assert record["approval_allowed"] is False
    assert record["report"]["rows"][1]["candidate_code"] is None
    reopened = get_record(client, auth, pid, record)
    assert reopened.json()["report"] == record["report"]
    assert reopened.headers["cache-control"] == "private, no-store"
    retry = client.post(base + "/reviews", headers=auth, json=body)
    assert retry.status_code == 200
    assert retry.json()["record"]["id"] == record["record"]["id"]
    assert client.post(base + "/reviews", headers=auth, json={**body, "title": "Another"}).status_code == 409
    assert len(client.get(base + "/reviews", headers=auth).json()["records"]) == 1


def test_source_change_between_preview_and_save_is_rejected(client, auth, source):
    _pid, _iid, base, _rows, body = prepared(client, auth)
    source.write_bytes(b"changed source")
    assert client.post(base + "/reviews", headers=auth, json=body).status_code == 409
    assert client.get(base + "/reviews", headers=auth).json()["records"] == []


def test_revision_change_marks_history_and_resume_uses_current_values(client, auth, source):
    (pid, _iid, base, rows, body), record = saved(client, auth)
    revise(client, auth, pid, rows[0])
    data = get_record(client, auth, pid, record).json()
    assert data["currentness"]["status"] == "changed"
    assert "METRAJ_CHANGED" in data["currentness"]["flags"]
    assert data["report"] == record["report"]
    assert data["resume_rows"][0]["revision_id"] is not None
    assert "5 mm" in data["resume_rows"][0]["effective_description"]
    assert data["approval_allowed"] is False
    assert client.post(base + "/reviews", headers=auth, json={**body, "request_key": str(uuid4())}).status_code == 409


def test_missing_or_changed_pdf_and_engine_are_explicit(client, auth, source, monkeypatch):
    (pid, _iid, _base, _rows, _body), record = saved(client, auth)
    source.write_bytes(b"different bytes")
    assert "PDF_CHANGED" in get_record(client, auth, pid, record).json()["currentness"]["flags"]
    source.unlink()
    data = get_record(client, auth, pid, record).json()
    assert data["currentness"]["status"] == "unverified"
    assert "PDF_UNVERIFIED" in data["currentness"]["flags"]
    monkeypatch.setattr(records, "engine_digest", lambda: "b" * 64)
    assert "ENGINE_CHANGED" in get_record(client, auth, pid, record).json()["currentness"]["flags"]


def test_integrity_tampering_is_not_displayed(client, auth, source):
    (pid, _iid, _base, _rows, _body), record = saved(client, auth)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    row = db.get(TechnicalReviewRecord, record["record"]["id"])
    row.snapshot_json = row.snapshot_json.replace('"744.50"', '"1.00"')
    db.commit()
    generator.close()
    result = get_record(client, auth, pid, record)
    assert result.status_code == 409
    assert "report" not in result.json()


def test_auth_tenant_and_project_isolation(client, auth, source):
    (pid, _iid, base, _rows, body), record = saved(client, auth)
    url = f"/api/projects/{pid}/a3/reviews/{record['record']['id']}"
    assert client.get(url).status_code == 401
    assert client.post(base + "/reviews", json=body).status_code == 401
    assert client.get(base + "/reviews").status_code == 401
    other = make_auth(client, "Other org", "other-review@example.com")
    assert client.get(url, headers=other).status_code == 404
    assert client.get(base + "/reviews", headers=other).status_code == 404
    assert client.post(base + "/reviews", headers=other, json=body).status_code == 404
    other_pid, _iid2, _base2, _rows2 = imported(client, auth)
    assert client.get(f"/api/projects/{other_pid}/a3/reviews/{record['record']['id']}", headers=auth).status_code == 404
    assert client.delete(url, headers=auth).status_code == 405
    assert client.put(url, headers=auth, json={}).status_code == 405


def test_exclusion_preserves_history_but_forbids_resume(client, auth, source):
    (pid, iid, base, _rows, body), record = saved(client, auth)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    user = db.scalar(select(User))
    db.add(MetrajImportExclusion(import_id=iid, organization_id=user.organization_id,
        project_id=pid, original_sha256=record["report"]["import_source"]["sha256"],
        excluded_by_id=user.id, reason="Synthetic exclusion"))
    db.commit()
    generator.close()
    data = get_record(client, auth, pid, record).json()
    assert data["resume_allowed"] is False
    assert data["resume_rows"] == []
    assert "IMPORT_EXCLUDED" in data["currentness"]["flags"]
    assert client.post(base + "/reviews", headers=auth, json={**body, "request_key": str(uuid4())}).status_code == 409


@pytest.mark.parametrize("extra", [{"report": {"approval_allowed": True}}, {"pdf_path": "C:/fake.pdf"},
                                  {"title": "   "}, {"rows": []}])
def test_untrusted_results_and_paths_are_rejected(client, auth, source, extra):
    _pid, _iid, base, _rows, body = prepared(client, auth)
    assert client.post(base + "/reviews", headers=auth, json={**body, **extra}).status_code == 422


def test_saving_only_inserts_review_records(client, auth, source):
    from sqlalchemy import event

    _pid, _iid, base, _rows, body = prepared(client, auth)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    engine = db.get_bind()
    generator.close()
    writes = []
    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.post(base + "/reviews", headers=auth, json=body)
        assert response.status_code == 201, response.text
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(writes) == 1
    assert "INSERT INTO technical_review_records" in writes[0]


def test_list_pagination_is_bounded(client, auth, source):
    (_pid, _iid, base, _rows, _body), result = saved(client, auth)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    original = db.get(TechnicalReviewRecord, result["record"]["id"])
    for _ in range(20):
        db.add(TechnicalReviewRecord(organization_id=original.organization_id,
            project_id=original.project_id, import_id=original.import_id,
            created_by_id=original.created_by_id, title=original.title,
            row_count=original.row_count, request_key=str(uuid4()), request_sha256="a" * 64,
            snapshot_json=original.snapshot_json, snapshot_sha256=original.snapshot_sha256))
    db.commit()
    generator.close()
    first = client.get(base + "/reviews", headers=auth).json()
    last = client.get(base + "/reviews?offset=20", headers=auth).json()
    assert len(first["records"]) == 20
    assert first["next_offset"] == 20
    assert len(last["records"]) == 1
    assert last["next_offset"] is None
    assert not ({r["id"] for r in first["records"]} & {r["id"] for r in last["records"]})
