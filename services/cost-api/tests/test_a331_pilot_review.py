"""A3.31 pilot acceptance remains separate from qualified engineering and M5."""
from uuid import uuid4

from app import a331_pilot_review_api as pilot_api
from app.a331_pilot_review_store import PilotTechnicalReviewEvent
from app.database import get_db
from test_a330_editable_engineering import (
    proposal, setup_project, state as analysis_state,
)


def pilot_state(client, auth, url):
    r = client.get(url + "/pilot/state", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def request(current, action, **overrides):
    data = {
        "action": action,
        "expected_source_fingerprint": current["source_fingerprint"],
        "expected_analysis_revision_id": current["analysis_revision_id"],
        "expected_previous_event_id":
            current["last_event"]["id"] if current["last_event"] else None,
        "request_key": str(uuid4()),
        "acknowledgement": "I_REVIEWED_SOURCE_AND_THIS_IS_NOT_ENGINEER_SIGNOFF",
    }
    return {**data, **overrides}


def prepare(client, auth, monkeypatch):
    _, _, _, base = setup_project(client, auth, monkeypatch)
    before = analysis_state(client, auth, base)
    saved = client.post(
        base + "/analysis/revisions", headers=auth, json=proposal(before),
    )
    assert saved.status_code == 201, saved.text
    return base, base.replace("/a330/", "/a331/")


def test_position_list_pilot_status_follows_saved_decisions_and_revisions(
    client, auth, monkeypatch,
):
    from app import a327_engineer_handoff
    from app import a330_editable_analysis as analysis_api

    _, _, _, probe = setup_project(client, auth, monkeypatch)
    catalog = analysis_api.read_analysis(None)
    monkeypatch.setattr(a327_engineer_handoff, "read_analysis_pdf",
                        lambda user: catalog)
    # The dedicated A3.30 endpoint includes project, import, and item IDs.
    parts = probe.split("/")
    pid, iid, item_id = parts[3], parts[6], parts[8]
    decision_url = probe.replace("/a330/", "/a331/")
    list_url = f"/api/projects/{pid}/a327/imports/{iid}/readiness?offset=0&limit=20"

    def list_row():
        response = client.get(list_url, headers=auth)
        assert response.status_code == 200, response.text
        entry = next(
            r for r in response.json()["rows"] if r["work_item_id"] == item_id
        )
        assert entry["engineering_approved"] is False
        assert entry["cost_allowed"] is False
        return entry

    initial = list_row()
    assert initial["pilot_confirmed"] is False
    assert initial["pilot_status"] == "none"

    before = analysis_state(client, auth, probe)
    assert client.post(probe + "/analysis/revisions", headers=auth,
                       json=proposal(before)).status_code == 201
    current = pilot_state(client, auth, decision_url)
    assert current["evidence_ready"] is True
    assert client.post(decision_url + "/pilot/decisions", headers=auth,
                       json=request(current, "accept")).status_code == 201

    accepted = list_row()
    assert accepted["pilot_confirmed"] is True
    assert accepted["pilot_status"] == "confirmed"
    assert accepted["saved_candidate"] == "15.225.1004"
    # A page reload still reads the persisted source-bound acceptance.
    assert list_row()["pilot_status"] == "confirmed"

    current = pilot_state(client, auth, decision_url)
    assert client.post(decision_url + "/pilot/decisions", headers=auth,
                       json=request(current, "reopen")).status_code == 201
    reopened = list_row()
    assert reopened["pilot_confirmed"] is False
    assert reopened["pilot_status"] == "reopened"

    current = pilot_state(client, auth, decision_url)
    assert client.post(decision_url + "/pilot/decisions", headers=auth,
                       json=request(current, "accept")).status_code == 201
    latest = analysis_state(client, auth, probe)
    assert client.post(probe + "/analysis/revisions", headers=auth,
                       json=proposal(latest, reason="")).status_code == 201
    stale = list_row()
    assert stale["pilot_confirmed"] is False
    assert stale["pilot_status"] == "stale"


def test_admin_user_can_confirm_pilot_review_without_engineer_role(
    client, auth, monkeypatch,
):
    a330, url = prepare(client, auth, monkeypatch)
    current = pilot_state(client, auth, url)
    assert current["evidence_ready"] is True
    assert current["pilot_confirmed"] is False
    assert current["engineering_approved"] is False

    payload = request(current, "accept")
    accepted = client.post(url + "/pilot/decisions", headers=auth, json=payload)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["pilot_confirmed"] is True
    assert accepted.json()["engineering_approved"] is False
    assert accepted.json()["cost_allowed"] is False
    refreshed = pilot_state(client, auth, url)
    assert refreshed["pilot_confirmed"] is True
    assert refreshed["last_event"]["reason"] == "Gerekçe belirtilmedi"
    assert analysis_state(client, auth, a330)["engineering"]["engineering_approved"] is False
    assert analysis_state(client, auth, a330)["engineering"]["cost_allowed"] is False

    retry = client.post(url + "/pilot/decisions", headers=auth, json=payload)
    assert retry.status_code == 200
    assert retry.json()["id"] == refreshed["last_event"]["id"]
    conflict = client.post(url + "/pilot/decisions", headers=auth, json={
        **payload, "action": "reopen",
    })
    assert conflict.status_code == 409


def test_pilot_reopen_records_history_and_prevents_duplicate_confirmation(
    client, auth, monkeypatch,
):
    _, url = prepare(client, auth, monkeypatch)
    before = pilot_state(client, auth, url)
    first = client.post(url + "/pilot/decisions", headers=auth,
                        json=request(before, "accept"))
    assert first.status_code == 201, first.text
    now = pilot_state(client, auth, url)
    assert client.post(url + "/pilot/decisions", headers=auth,
                       json=request(now, "accept")).status_code == 409
    reopened = client.post(url + "/pilot/decisions", headers=auth,
                           json=request(now, "reopen", reason="Tekrar bakacağım"))
    assert reopened.status_code == 201, reopened.text
    assert pilot_state(client, auth, url)["pilot_confirmed"] is False
    assert pilot_state(client, auth, url)["last_event"]["action"] == "reopen"
    fresh = pilot_state(client, auth, url)
    assert client.post(url + "/pilot/decisions", headers=auth,
                       json=request(fresh, "accept")).status_code == 201


def test_later_analysis_revision_invalidates_pilot_acceptance(
    client, auth, monkeypatch,
):
    a330, url = prepare(client, auth, monkeypatch)
    before = pilot_state(client, auth, url)
    assert client.post(url + "/pilot/decisions", headers=auth,
                       json=request(before, "accept")).status_code == 201
    analysis = analysis_state(client, auth, a330)
    updated = client.post(a330 + "/analysis/revisions", headers=auth,
                          json=proposal(analysis, reason=""))
    assert updated.status_code == 201, updated.text
    old = pilot_state(client, auth, url)
    assert old["pilot_confirmed"] is False
    assert old["last_event"]["source_current"] is False
    assert old["cost_allowed"] is False
    assert client.post(url + "/pilot/decisions", headers=auth,
                       json=request(before, "accept")).status_code == 409


def test_pilot_acceptance_requires_evidence_and_explicit_acknowledgement(
    client, auth, monkeypatch,
):
    _, url = prepare(client, auth, monkeypatch)
    before = pilot_state(client, auth, url)
    forged = request(before, "accept",
                     acknowledgement="I_AM_AN_ENGINEER")
    assert client.post(url + "/pilot/decisions", headers=auth,
                       json=forged).status_code == 422
    real_source = pilot_api._source

    def unresolved_source(*args, **kwargs):
        row, fingerprint, position, digest = real_source(*args, **kwargs)
        return {**row, "status": "needs_document"}, fingerprint, position, digest

    monkeypatch.setattr(pilot_api, "_source", unresolved_source)
    denied = client.post(url + "/pilot/decisions", headers=auth,
                         json=request(before, "accept"))
    assert denied.status_code == 409, denied.text
    assert pilot_state(client, auth, url)["pilot_confirmed"] is False


def test_pilot_decision_never_writes_engineering_signoffs(client, auth, monkeypatch):
    a330, url = prepare(client, auth, monkeypatch)
    before = pilot_state(client, auth, url)
    assert client.post(url + "/pilot/decisions", headers=auth,
                       json=request(before, "accept")).status_code == 201
    session = client.app.dependency_overrides[get_db]()
    db = next(session)
    try:
        from sqlalchemy import select
        from app.a330_review_store import EngineeringSignoff
        assert db.scalar(select(EngineeringSignoff)) is None
        assert db.scalar(select(PilotTechnicalReviewEvent)) is not None
    finally:
        session.close()
