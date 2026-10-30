"""A3.27.2: preparation notes are evidence-bound and never engineering approval."""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app import a327_decisions
from app.database import get_db
from app.models import PdfCandidateSelection, User, WorkItem
from test_a326_project_evidence import attach, pdf, project_with_metraj


def endpoint(pid, iid, item_id):
    return f"/api/projects/{pid}/a327/imports/{iid}/items/{item_id}"


def recorded_project(client, auth, monkeypatch):
    pid, iid, items = project_with_metraj(client, auth)
    assert attach(
        client, auth, pid,
        pdf("Gazbeton 10 cm duvar: 2,50 N/mm2 400 kg/m3"),
    ).status_code == 201
    sha = "a" * 64
    monkeypatch.setattr(
        a327_decisions, "read_analysis_pdf",
        lambda user: (sha, (SimpleNamespace(
            id="15.225.1004",
            description="Gazbeton 10 cm 2,50 N/mm2 400 kg/m3",
        ),)),
    )
    gen = client.app.dependency_overrides[get_db]()
    session = next(gen)
    owner = session.scalar(select(User))
    session.add(PdfCandidateSelection(
        organization_id=owner.organization_id,
        project_id=pid, import_id=iid, work_item_id=items[0],
        selected_by_id=owner.id, revision_id=None,
        pdf_sha256=sha, position_code="15.225.1004",
    ))
    session.commit()
    gen.close()
    return pid, iid, items


def test_handoff_preparation_records_actor_reason_and_source_without_approval(
    client, auth, monkeypatch,
):
    pid, iid, items = recorded_project(client, auth, monkeypatch)
    url = endpoint(pid, iid, items[0])
    state = client.get(url + "/decision-state", headers=auth)
    assert state.status_code == 200, state.text
    before = state.json()
    assert before["status"] == "documented_for_review"
    assert "submit_for_engineering_review" in before["allowed_actions"]
    payload = {
        "action": "submit_for_engineering_review",
        "reason": "Gazbeton dayanim ve yogunluk kaynagi incelenmek uzere iletildi.",
        "expected_source_fingerprint": before["source_fingerprint"],
        "expected_previous_id": None,
        "request_key": str(uuid4()),
        "confirmation": "I_REVIEWED_SOURCE_EVIDENCE",
    }
    first = client.post(url + "/decisions", headers=auth, json=payload)
    assert first.status_code == 201, first.text
    event = first.json()
    assert event["candidate_code"] == "15.225.1004"
    assert event["created_by_id"]
    assert event["document_sha256"]
    assert event["engineering_approved"] is False
    assert event["approval_allowed"] is False
    assert event["cost_allowed"] is False

    repeated = client.post(url + "/decisions", headers=auth, json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["id"] == event["id"]
    next_state = client.get(url + "/decision-state", headers=auth).json()
    assert next_state["latest_id"] == event["id"]

    bad_request = {**payload, "reason": "Different review note"}
    assert client.post(url + "/decisions", headers=auth, json=bad_request).status_code == 409
    forbidden = {**payload, "action": "approve", "request_key": str(uuid4())}
    assert client.post(url + "/decisions", headers=auth, json=forbidden).status_code == 422


def test_preapproval_record_refuses_stale_sources_and_outdated_history(
    client, auth, monkeypatch,
):
    pid, iid, items = recorded_project(client, auth, monkeypatch)
    url = endpoint(pid, iid, items[0])
    before = client.get(url + "/decision-state", headers=auth).json()
    payload = {
        "action": "request_information",
        "reason": "Teknik belgede kapsamin kontrol edilmesi gerekli.",
        "expected_source_fingerprint": before["source_fingerprint"],
        "expected_previous_id": None,
        "request_key": str(uuid4()),
        "confirmation": "I_REVIEWED_SOURCE_EVIDENCE",
    }
    assert client.post(url + "/decisions", headers=auth, json=payload).status_code == 201

    stale_history = {**payload, "request_key": str(uuid4())}
    assert client.post(url + "/decisions", headers=auth, json=stale_history).status_code == 409

    state = client.get(url + "/decision-state", headers=auth).json()
    second = {
        **payload, "expected_previous_id": state["latest_id"],
        "request_key": str(uuid4()),
    }
    monkeypatch.setattr(
        a327_decisions, "read_analysis_pdf", lambda user: ("b" * 64, ())
    )
    changed = client.post(url + "/decisions", headers=auth, json=second)
    assert changed.status_code == 409
    changed_state = client.get(url + "/decision-state", headers=auth).json()
    assert changed_state["status"] == "stale_candidate"
    assert "submit_for_engineering_review" not in changed_state["allowed_actions"]


def test_unauthorized_and_missing_sources_never_submit_for_approval(client, auth):
    pid, iid, items = project_with_metraj(client, auth)
    url = endpoint(pid, iid, items[0])
    before = client.get(url + "/decision-state", headers=auth)
    assert before.status_code == 200
    assert before.json()["allowed_actions"] == ["request_information"]
    attempted = {
        "action": "submit_for_engineering_review",
        "reason": "Yeterli kaynak yokken sevk olusturulamaz.",
        "expected_source_fingerprint": before.json()["source_fingerprint"],
        "expected_previous_id": None, "request_key": str(uuid4()),
        "confirmation": "I_REVIEWED_SOURCE_EVIDENCE",
    }
    assert client.post(url + "/decisions", headers=auth, json=attempted).status_code == 409
    reg = client.post("/api/auth/register", json={
        "organization_name": "Second firm",
        "email": "a327-decision-other@example.com",
        "password": "secure-pilot-password",
    })
    assert reg.status_code == 201
    other = {"Authorization": "Bearer " + reg.json()["access_token"]}
    assert client.get(url + "/decision-state", headers=other).status_code == 404
    assert client.post(url + "/decisions", headers=other, json=attempted).status_code == 404
