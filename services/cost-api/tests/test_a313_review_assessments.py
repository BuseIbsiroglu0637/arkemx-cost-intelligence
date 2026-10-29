"""Evidence and authorization boundaries of non-approval review assessments."""
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from test_a312_review_records import revise, saved, source  # noqa: F401
from test_m41 import auth as make_auth

from app import a3_review_records
from app.a3_assessment_store import TechnicalReviewAssessment as Assessment
from app.a3_review_store import TechnicalReviewRecord
from app.database import get_db
from app.models import MetrajImportExclusion, User


def setup(client, auth):
    (pid, iid, _base, rows, _body), record = saved(client, auth)
    url = f"/api/projects/{pid}/a3/reviews/{record['record']['id']}/assessments"
    body = {"work_item_id": rows[0]["work_item_id"], "action": "reject_candidate",
            "reason": "Ince siva dozaji sartnameyi karsilamiyor.",
            "expected_snapshot_sha256": record["record"]["snapshot_sha256"],
            "expected_previous_id": None, "request_key": str(uuid4())}
    return pid, iid, url, body, record, rows


def history(client, auth, url, body, **params):
    return client.get(url, params={"work_item_id": body["work_item_id"], **params}, headers=auth)


def test_reopen_history_preserves_evidence_and_never_approves(client, auth, source):
    _pid, _iid, url, body, original, _rows = setup(client, auth)
    created = client.post(url, headers=auth, json=body)
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["candidate_code"] == "15.275.1111"
    assert data["snapshot_sha256"] == original["record"]["snapshot_sha256"]
    assert data["revision_id"] == original["report"]["rows"][0]["identity"]["revision_id"]
    assert data["created_by_id"] and data["created_at"]
    assert data["approval_allowed"] is False and data["engineering_approval"] is False
    reopened = history(client, auth, url, body)
    assert reopened.status_code == 200
    assert reopened.headers["cache-control"] == "private, no-store"
    assert reopened.json()["events"] == [data]
    assert reopened.json()["latest_id"] == data["id"]
    assert client.get(url.removesuffix("/assessments"), headers=auth).json()["report"] == original["report"]


def test_retry_conflict_and_optimistic_history(client, auth, source):
    _pid, _iid, url, body, _record, _rows = setup(client, auth)
    first = client.post(url, headers=auth, json=body)
    retry = client.post(url, headers=auth, json=body)
    assert retry.status_code == 200 and retry.json()["id"] == first.json()["id"]
    assert client.post(url, headers=auth, json={**body, "reason": "Different reason for same key"}).status_code == 409
    second = {**body, "action": "request_information", "request_key": str(uuid4())}
    assert client.post(url, headers=auth, json=second).status_code == 409
    second["expected_previous_id"] = first.json()["id"]
    newer = client.post(url, headers=auth, json=second)
    assert newer.status_code == 201
    events = history(client, auth, url, body).json()["events"]
    assert [e["action"] for e in events] == ["request_information", "reject_candidate"]
    assert events[0]["previous_id"] == first.json()["id"]


@pytest.mark.parametrize("change", ["revision", "pdf", "missing_pdf", "engine", "excluded", "hash", "corruption"])
def test_changed_unknown_or_corrupt_evidence_blocks_assessment(client, auth, source, monkeypatch, change):
    pid, iid, url, body, record, rows = setup(client, auth)
    if change == "revision":
        revise(client, auth, pid, rows[0])
    elif change == "pdf":
        source.write_bytes(b"changed PDF")
    elif change == "missing_pdf":
        source.unlink()
    elif change == "engine":
        monkeypatch.setattr(a3_review_records, "engine_digest", lambda: "d" * 64)
    elif change == "hash":
        body["expected_snapshot_sha256"] = "f" * 64
    else:
        generator = client.app.dependency_overrides[get_db]()
        db = next(generator)
        if change == "corruption":
            db.get(TechnicalReviewRecord, record["record"]["id"]).snapshot_json = "{}"
        else:
            user = db.scalar(select(User))
            db.add(MetrajImportExclusion(import_id=iid, organization_id=user.organization_id,
                project_id=pid, original_sha256=record["report"]["import_source"]["sha256"],
                excluded_by_id=user.id, reason="Synthetic exclusion"))
        db.commit()
        generator.close()
    result = client.post(url, headers=auth, json=body)
    assert result.status_code == 409, result.text


def test_history_survives_source_change_and_retry_does_not_write_again(client, auth, source):
    _pid, _iid, url, body, _record, _rows = setup(client, auth)
    first = client.post(url, headers=auth, json=body)
    source.unlink()
    data = history(client, auth, url, body).json()
    assert data["assessment_allowed"] is False
    assert data["events"][0]["id"] == first.json()["id"]
    assert client.post(url, headers=auth, json=body).status_code == 200


def test_auth_scope_and_snapshot_row_identity(client, auth, source):
    pid, _iid, url, body, _record, _rows = setup(client, auth)
    assert client.post(url, json=body).status_code == 401
    assert history(client, {}, url, body).status_code == 401
    other = make_auth(client, "Assessment outsider", "assessment-other@example.com")
    assert client.post(url, headers=other, json=body).status_code == 404
    assert history(client, other, url, body).status_code == 404
    assert client.post(url.replace(pid, str(uuid4())), headers=auth, json=body).status_code == 404
    missing = {**body, "work_item_id": str(uuid4())}
    assert client.post(url, headers=auth, json=missing).status_code == 404
    assert history(client, auth, url, missing).status_code == 404


@pytest.mark.parametrize("extra", [{"action": "approve"}, {"reason": " " * 20},
    {"reason": "short"}, {"candidate_code": "FAKE"}, {"revision_id": str(uuid4())},
    {"report": {}}, {"reason": "x" * 1001}, {"expected_snapshot_sha256": "xyz"}])
def test_untrusted_or_incomplete_assessments_rejected(client, auth, source, extra):
    _pid, _iid, url, body, _record, _rows = setup(client, auth)
    assert client.post(url, headers=auth, json={**body, **extra}).status_code == 422


def test_missing_candidate_can_request_information_but_cannot_reject(client, auth, source):
    _pid, _iid, url, body, _record, rows = setup(client, auth)
    body["work_item_id"] = rows[1]["work_item_id"]
    assert client.post(url, headers=auth, json=body).status_code == 409
    body["action"] = "request_information"
    result = client.post(url, headers=auth, json=body)
    assert result.status_code == 201 and result.json()["candidate_code"] is None


def test_only_appends_assessment_and_no_edit_or_delete_routes(client, auth, source):
    _pid, _iid, url, body, _record, _rows = setup(client, auth)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    engine = db.get_bind()
    generator.close()
    writes = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.post(url, headers=auth, json=body)
        assert response.status_code == 201, response.text
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(writes) == 1 and "INSERT INTO technical_review_assessments" in writes[0]
    assert client.put(url, headers=auth, json=body).status_code == 405
    assert client.delete(url, headers=auth).status_code == 405


def test_database_prevents_two_successors_to_same_history_event(client, auth, source):
    _pid, _iid, url, body, _record, _rows = setup(client, auth)
    response = client.post(url, headers=auth, json=body)
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    original = db.get(Assessment, response.json()["id"])
    fields = {c.name: getattr(original, c.name) for c in Assessment.__table__.columns
              if c.name not in ("id", "request_key")}
    db.add(Assessment(**fields, request_key=str(uuid4())))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    generator.close()
