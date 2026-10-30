"""A3.40: saved single-layer plaster positions can be edited and piloted.

This is a DEMO human pilot checkpoint, never engineering signoff or official cost.
"""
from dataclasses import replace
from uuid import uuid4

from app.a327_engineer_handoff import _row_status
from test_a326_project_evidence import attach, pdf
from test_a335_plaster_poz_matching import _setup_pdf_pair, position


def _fixture_positions():
    ingredient = ({
        "code": "10.100.1062", "description": "Düz işçi",
        "unit": "Sa", "quantity": "0,25", "unit_price": "205,00",
        "amount": "51,25",
    },)
    coarse = replace(position(
        "15.275.1116", "250 kg çimento dozlu harç ile kaba sıva yapılması",
    ), ingredients=ingredient)
    fine = replace(position(
        "15.275.1115", "350 kg çimento dozlu harçla tek kat ince sıva yapılması",
    ), ingredients=ingredient)
    return coarse, fine


def _demo(client, auth, monkeypatch, doc=None):
    positions = _fixture_positions()
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch, positions=positions,
    )
    if doc is None:
        doc = pdf(
            "DEMO ORNEK: Gercek proje veya mesleki onay degildir.",
            "20 mm kaba siva; 8 mm ince siva.",
            "20 mm cimento esasli kaba siva 250 kg cimento dozlu.",
            "8 mm ince siva 350 kg cimento dozlu.",
        )
    linked = attach(client, auth, pid, doc)
    assert linked.status_code == 201, linked.text
    root = f"/api/projects/{pid}"
    url = f"{root}/a318/imports/{iid}"
    result = client.get(url + "/suggestions", headers=auth)
    assert result.status_code == 200, result.text
    rows = result.json()["rows"]
    assert len(rows) == 2
    for row, position_row in zip(rows, positions):
        saved = client.post(
            f"{url}/items/{row['work_item_id']}/candidate",
            headers=auth, json={
                "position_code": position_row.id,
                "expected_revision_id": row["revision_id"],
                "expected_pdf_sha256": sha,
            },
        )
        assert saved.status_code == 200, saved.text
    return pid, iid, rows, positions


def _analysis(root, iid, row):
    return (
        f"{root}/a330/imports/{iid}/items/{row['work_item_id']}"
    )


def _pilot(root, iid, row):
    return (
        f"{root}/a331/imports/{iid}/items/{row['work_item_id']}"
    )


def test_demo_coarse_and_fine_can_load_edit_and_complete_pilot_without_engineer(
    client, auth, monkeypatch,
):
    pid, iid, rows, positions = _demo(client, auth, monkeypatch)
    root = f"/api/projects/{pid}"
    states = client.get(
        f"{root}/a327/imports/{iid}/readiness", headers=auth,
    ).json()["rows"]
    assert [r["status"] for r in states] == [
        "documented_for_review", "documented_for_review",
    ]
    assert [r["saved_candidate"] for r in states] == [p.id for p in positions]
    for row, pos in zip(rows, positions):
        path = _analysis(root, iid, row)
        response = client.get(path + "/analysis", headers=auth)
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["candidate_code"] == pos.id
        assert state["engineering"]["evidence_ready"] is True
        assert state["engineering"]["engineering_approved"] is False
        assert state["engineering"]["cost_allowed"] is False
        assert len(state["source_inputs"]) == 1
        revision = client.post(
            path + "/analysis/revisions", headers=auth, json={
                "items": [{
                    "code": "10.100.1062", "description": "Düz işçi",
                    "unit": "Sa", "quantity": "0,25",
                    "unit_price": "205,00",
                }],
                "expected_source_fingerprint": state["source_fingerprint"],
                "expected_previous_revision_id": None,
                "request_key": str(uuid4()),
                "reason": "",
            },
        )
        assert revision.status_code == 201, revision.text
        assert revision.json()["source_current"] is True

        pilot_path = _pilot(root, iid, row)
        state_pilot = client.get(pilot_path + "/pilot/state", headers=auth)
        assert state_pilot.status_code == 200, state_pilot.text
        facts = state_pilot.json()
        assert facts["evidence_ready"] is True
        assert facts["pilot_confirmed"] is False
        decision = client.post(
            pilot_path + "/pilot/decisions", headers=auth, json={
                "action": "accept",
                "expected_source_fingerprint": facts["source_fingerprint"],
                "expected_analysis_revision_id": facts["analysis_revision_id"],
                "expected_previous_event_id": None,
                "request_key": str(uuid4()),
                "acknowledgement": "I_REVIEWED_SOURCE_AND_THIS_IS_NOT_ENGINEER_SIGNOFF",
            },
        )
        assert decision.status_code == 201, decision.text
        assert decision.json()["pilot_confirmed"] is True
        assert decision.json()["engineering_approved"] is False
        assert decision.json()["cost_allowed"] is False

    fresh = client.get(f"{root}/a327/imports/{iid}/readiness", headers=auth).json()["rows"]
    assert all(r["pilot_confirmed"] and r["pilot_status"] == "confirmed" for r in fresh)
    assert all(not r["engineering_approved"] and not r["cost_allowed"] for r in fresh)


def test_incomplete_project_dose_allows_draft_but_not_pilot(
    client, auth, monkeypatch,
):
    pid, iid, rows, positions = _demo(
        client, auth, monkeypatch, doc=pdf("20 mm kaba siva; 8 mm ince siva."),
    )
    root=f"/api/projects/{pid}"
    state=client.get(f"{root}/a327/imports/{iid}/readiness",headers=auth).json()["rows"][0]
    assert state["status"] == "document_evidence_for_review"
    assert state["saved_candidate"] == positions[0].id
    draft=client.get(_analysis(root,iid,rows[0])+"/analysis",headers=auth)
    assert draft.status_code == 200, draft.text
    assert draft.json()["engineering"]["evidence_ready"] is False
    pilot=client.get(_pilot(root,iid,rows[0])+"/pilot/state",headers=auth)
    assert pilot.status_code == 200, pilot.text
    assert pilot.json()["evidence_ready"] is False


def test_dose_disagreement_keeps_pilot_blocked(
    client,auth,monkeypatch,
):
    pid,iid,rows,_=_demo(client,auth,monkeypatch,doc=pdf(
        "20 mm kaba siva 350 kg cimento dozlu.",
        "8 mm ince siva 350 kg cimento dozlu.",
    ))
    root=f"/api/projects/{pid}"
    ready=client.get(f"{root}/a327/imports/{iid}/readiness",headers=auth).json()["rows"][0]
    assert ready["status"] != "documented_for_review"
    draft=client.get(_analysis(root,iid,rows[0])+"/analysis",headers=auth)
    assert draft.status_code == 200
    assert draft.json()["engineering"]["evidence_ready"] is False
