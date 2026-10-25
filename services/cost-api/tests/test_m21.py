"""M2.1 acceptance tests: immutable source, review, incremental matching and isolation."""
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy import select
from app.models import WorkItem, WorkItemRevision, MatchRun, MatchDecision


def auth(client, org, email):
    result = client.post("/api/auth/register", json={
        "organization_name": org, "email": email, "password": "valid-test-password-123"
    })
    assert result.status_code == 201, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def uploaded(rows):
    workbook = Workbook()
    ws = workbook.active
    ws.append(["İmalat Açıklaması", "Miktar", "Birim"])
    for row in rows:
        ws.append(row)
    target = BytesIO()
    workbook.save(target)
    return target.getvalue()


def setup(client, headers):
    created = client.post("/api/projects", headers=headers, json={"name": "M2.1 Deneme"})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    data = uploaded([
        ["Porselen seramik kaplama 60x60", "245,50", "m2"],
        ["Gazbeton duvar 10 cm", "1.234", "m2"],
        ["Hazır beton dökümü", "10,50", "m3"],
        ["Kapı montajı", 4, "adet"],
        ["Boya işleri", 15, "kutu"],
    ])
    assert client.post(f"/api/projects/{pid}/imports",
                       headers=headers, files={"file": ("metraj.xlsx", data)}).status_code == 201
    assert client.post("/api/m2/demo-catalog", headers=headers).status_code == 201
    run = client.post(f"/api/projects/{pid}/m2/run", headers=headers, json={})
    assert run.status_code == 201, run.text
    return pid, run.json()


def get_rows(client, headers, pid):
    response = client.get(f"/api/projects/{pid}/m21/items", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def correct(client, headers, pid, row, quantity, unit, description=None, revision=0):
    return client.post(f"/api/projects/{pid}/m21/items/{row['id']}/revisions",
                       headers=headers,
                       json={"description": description or row["effective"]["description"],
                             "quantity": quantity, "unit": unit,
                             "reason": "Teknik proje üzerinden kontrol edildi",
                             "expected_revision": revision})


def test_saved_revision_preserves_original_and_adds_history(client):
    headers = auth(client, "Firma M21", "rev1@example.com")
    pid, _ = setup(client, headers)
    rows = get_rows(client, headers, pid)
    gaz = rows[1]
    assert gaz["original"]["quantity"] == "1.234"
    assert gaz["effective"]["quantity"] is None
    response = correct(client, headers, pid, gaz, "1234", "m2")
    assert response.status_code == 201, response.text
    assert response.json()["requires_rematch"] is True
    rows_after = get_rows(client, headers, pid)
    assert rows_after[1]["original"]["quantity"] == "1.234"
    assert rows_after[1]["effective"]["quantity"] == "1234.0000"
    assert rows_after[1]["effective"]["review_required"] is False
    assert rows_after[1]["revision"] == 1
    history = client.get(f"/api/projects/{pid}/m21/items/{gaz['id']}/history",
                         headers=headers).json()
    assert history["original"]["quantity"] == "1.234"
    assert len(history["revisions"]) == 1
    assert history["revisions"][0]["reason"] == "Teknik proje üzerinden kontrol edildi"
    # Previously stored M1 row should stay exactly as imported.
    before = client.get(f"/api/projects/{pid}/items", headers=headers).json()
    assert before[1]["quantity"] is None
    assert before[1]["raw_quantity"] == "1.234"


def test_conflicts_and_ambiguous_or_unknown_values(client):
    headers = auth(client, "Firma Kontrol", "rev2@example.com")
    pid, _ = setup(client, headers)
    gaz, paint = get_rows(client, headers, pid)[1], get_rows(client, headers, pid)[4]
    ambiguous = correct(client, headers, pid, gaz, "1.234", "m2")
    assert ambiguous.status_code == 422
    invalid = correct(client, headers, pid, paint, "15", "kutu")
    assert invalid.status_code == 422
    saved = correct(client, headers, pid, gaz, "1234", "m2")
    assert saved.status_code == 201
    stale = correct(client, headers, pid, gaz, "123", "m2", revision=0)
    assert stale.status_code == 409
    duplicate = correct(client, headers, pid, gaz, "1234", "m2", revision=1)
    assert duplicate.status_code == 409
    corrected_again = correct(client, headers, pid, gaz, "1235", "m2", revision=1)
    assert corrected_again.status_code == 201
    history = client.get(f"/api/projects/{pid}/m21/items/{gaz['id']}/history",
                         headers=headers).json()
    assert [rev["revision"] for rev in history["revisions"]] == [1,2]


def test_only_changed_rows_recomputed_and_old_approvals_kept_historically(client):
    headers = auth(client, "Firma Eslestirme", "rev3@example.com")
    pid, original_run = setup(client, headers)
    original = client.get(f"/api/projects/{pid}/m2/latest", headers=headers).json()
    first_candidate = original["items"][0]["candidates"][0]
    approve = client.post(f"/api/projects/{pid}/m2/decisions", headers=headers, json={
        "run_id": original_run["id"], "candidate_id": first_candidate["id"], "action": "approve"
    })
    assert approve.status_code == 201, approve.text

    gaz, paint = get_rows(client, headers, pid)[1], get_rows(client, headers, pid)[4]
    assert correct(client, headers, pid, gaz, "1234", "m2").status_code == 201
    assert correct(client, headers, pid, paint, "15", "m2").status_code == 201
    # Old approval was on an unaffected item; prior frozen results still preserved.
    stale = client.get(f"/api/projects/{pid}/m2/latest", headers=headers).json()
    assert stale["items"][1]["stale"] is True
    assert stale["items"][4]["stale"] is True
    assert stale["items"][0]["stale"] is False
    assert stale["items"][0]["decision"]["action"] == "approve"

    rerun = client.post(f"/api/projects/{pid}/m21/rematch", headers=headers)
    assert rerun.status_code == 201, rerun.text
    data = rerun.json()
    assert data["recomputed_item_count"] == 2
    assert data["copied_item_count"] == 3
    assert data["parent_run_id"] == original_run["id"]
    latest = client.get(f"/api/projects/{pid}/m2/latest", headers=headers).json()
    assert latest["run"]["id"] == data["id"]
    assert len(latest["items"]) == 5
    assert latest["items"][1]["quantity"] == "1234.0000"
    assert latest["items"][1]["review_required"] is False
    assert latest["items"][4]["unit"] == "m²"
    assert all(not row["stale"] for row in latest["items"])
    # Both the original and new runs exist; earlier decision is not forged into new run.
    assert latest["items"][0]["decision"] is None
    recorded = client.get(f"/api/projects/{pid}/m21/run-history", headers=headers)
    assert recorded.status_code == 200
    assert len(recorded.json()) == 2
    historical = client.get(f"/api/projects/{pid}/m21/run-history/{original_run['id']}", headers=headers)
    assert historical.status_code == 200, historical.text
    assert historical.json()["items"][0]["candidates"][0]["decisions"][0]["action"] == "approve"
    assert historical.json()["items"][1]["quantity"] is None
    original_decision = client.post(f"/api/projects/{pid}/m2/decisions", headers=headers, json={
        "run_id": original_run["id"], "candidate_id": first_candidate["id"], "action": "approve"})
    assert original_decision.status_code == 409
    repeated = client.post(f"/api/projects/{pid}/m21/rematch", headers=headers)
    assert repeated.status_code == 409


def test_revised_item_cannot_be_approved_against_stale_candidate(client):
    headers = auth(client, "Firma Onay", "rev4@example.com")
    pid, original_run = setup(client, headers)
    snapshot = client.get(f"/api/projects/{pid}/m2/latest", headers=headers).json()
    seramic = get_rows(client, headers, pid)[0]
    candidate = snapshot["items"][0]["candidates"][0]
    assert candidate["approvable"]
    edited = correct(client, headers, pid, seramic, "245,5", "m2",
                     description="Porselen seramik kaplama 30x60")
    assert edited.status_code == 201
    denied = client.post(f"/api/projects/{pid}/m2/decisions", headers=headers,json={
        "run_id": original_run["id"], "candidate_id": candidate["id"], "action": "approve"
    })
    assert denied.status_code == 409
    assert client.post(f"/api/projects/{pid}/m21/rematch", headers=headers).status_code == 201
    fresh = client.get(f"/api/projects/{pid}/m2/latest", headers=headers).json()
    assert fresh["items"][0]["description"] == "Porselen seramik kaplama 30x60"
    # Old catalog with 60x60 cannot be silently approved as 30x60.
    assert all(not cand["approvable"] for cand in fresh["items"][0]["candidates"])


def test_other_organization_cannot_see_or_edit_revisions(client):
    a = auth(client, "Firma Ayrim A", "rev5a@example.com")
    b = auth(client, "Firma Ayrim B", "rev5b@example.com")
    pid, _ = setup(client, a)
    target = get_rows(client,a,pid)[1]
    assert client.get(f"/api/projects/{pid}/m21/items",headers=b).status_code == 404
    assert client.get(f"/api/projects/{pid}/m21/items/{target['id']}/history",headers=b).status_code == 404
    assert correct(client,b,pid,target,"1234","m2").status_code == 404
    assert client.post(f"/api/projects/{pid}/m21/rematch",headers=b).status_code == 404
