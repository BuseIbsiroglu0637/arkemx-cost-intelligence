"""A3.37: never confuse the *removal* of old plaster with new plastering."""
from sqlalchemy import select

from app import a318_pdf_api
from app.a335_plaster_matching import plaster_checks, plaster_operation
from app.a320_smart_matching import find_pdf_candidates
from app.database import get_db
from app.models import PdfCandidateSelection
from test_a335_plaster_poz_matching import (
    COARSE, FINE, _setup_pdf_pair, item, position,
)


REMOVAL = position("15.106.1104", "Her türlü iç sıva sökülmesi", "153.75")
COARSE_POZ = position(
    "15.275.1116", "250 kg çimento dozlu harç ile kaba sıva yapılması",
)
FINE_POZ = position(
    "15.275.1115", "350 kg çimento dozlu harçla tek kat ince sıva yapılması",
)


def test_plaster_operation_is_not_same_as_material_family():
    assert plaster_operation(COARSE) == "application"
    assert plaster_operation(FINE) == "application"
    assert plaster_operation("Her türlü iç sıva sökülmesi") == "removal"
    assert plaster_operation("Mevcut sıvanın kazınması") == "removal"
    assert plaster_operation("İç sıva tamiri") == "repair"
    assert plaster_operation("Sıva onarılması") == "repair"
    assert plaster_operation("Kaplama sökülmesi") is None


def test_removal_and_repair_are_not_new_plaster_candidates():
    for candidate in ("Her türlü iç sıva sökülmesi", "İç sıva tamiri"):
        blockers, _ = plaster_checks(COARSE, candidate)
        assert "PLASTER_OPERATION_MISMATCH" in blockers
    # Incidental preparation in long PDF scope is not the position's main job.
    blockers, _ = plaster_checks(
        COARSE,
        "20 mm çimento esaslı kaba sıva yapılması",
        scope="Mevcut sıvanın sökülmesi ve yeni sıva için yüzey hazırlanması.",
    )
    assert "PLASTER_OPERATION_MISMATCH" not in blockers


def test_new_plaster_search_excludes_removal_but_removal_metraj_can_use_it():
    all_positions = (REMOVAL, COARSE_POZ, FINE_POZ)
    coarse_candidates = find_pdf_candidates(item(COARSE), all_positions)
    fine_candidates = find_pdf_candidates(item(FINE), all_positions)
    assert all(row["position_id"] != REMOVAL.id for row in coarse_candidates)
    assert all(row["position_id"] != REMOVAL.id for row in fine_candidates)
    assert coarse_candidates[0]["position_id"] == COARSE_POZ.id
    assert fine_candidates[0]["position_id"] == FINE_POZ.id
    removal_matches = find_pdf_candidates(
        item("Her türlü iç sıva sökülmesi"), [REMOVAL],
    )
    assert removal_matches[0]["position_id"] == REMOVAL.id


def test_pdf_api_rejects_demolition_on_both_new_plaster_rows(
    client, auth, monkeypatch,
):
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch, positions=(REMOVAL, COARSE_POZ, FINE_POZ),
    )
    url = f"/api/projects/{pid}/a318/imports/{iid}"
    response = client.get(url + "/suggestions", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cost_allowed"] is False
    assert body["approval_allowed"] is False
    rows = body["rows"]
    assert len(rows) == 2
    assert rows[0]["suggestions"][0]["code"] == COARSE_POZ.id
    assert rows[1]["suggestions"][0]["code"] == FINE_POZ.id

    for row in rows:
        assert REMOVAL.id not in {
            entry["code"] for entry in row["suggestions"]
        }
        target = f"{url}/items/{row['work_item_id']}/candidate"
        denied = client.post(target, headers=auth, json={
            "position_code": REMOVAL.id,
            "expected_revision_id": row["revision_id"],
            "expected_pdf_sha256": sha,
        })
        assert denied.status_code == 422, denied.text
        # Wrong demolition cost cannot silently be attached by API.
        assert client.get(url + "/suggestions", headers=auth).json()["rows"][
            row["source_row"] - 2
        ]["saved_selection"] is None


def test_old_demolition_selection_is_stale_after_new_operation_gate(
    client, auth, monkeypatch,
):
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch, positions=(REMOVAL, COARSE_POZ, FINE_POZ),
    )
    url = f"/api/projects/{pid}/a318/imports/{iid}"
    row = client.get(url + "/suggestions", headers=auth).json()["rows"][0]
    endpoint = f"{url}/items/{row['work_item_id']}/candidate"
    saved = client.post(endpoint, headers=auth, json={
        "position_code": COARSE_POZ.id,
        "expected_revision_id": row["revision_id"],
        "expected_pdf_sha256": sha,
    })
    assert saved.status_code == 200, saved.text
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        stored = db.scalar(select(PdfCandidateSelection).where(
            PdfCandidateSelection.work_item_id == row["work_item_id"],
        ))
        stored.position_code = REMOVAL.id
        db.commit()
    finally:
        db.close()
    stale = client.get(url + "/suggestions", headers=auth).json()["rows"][0]
    assert stale["saved_selection"]["stale"] is True
    assert stale["saved_selection"]["stale_reason"] == "TECHNICAL_CONFLICT"
    assert stale["saved_selection"]["code"] is None
