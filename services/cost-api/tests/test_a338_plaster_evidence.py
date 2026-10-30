"""A3.38: exact sourced facts, no guessed project dosage or approvals."""
from app import a338_plaster_evidence as a338
from app.a338_plaster_evidence import compare_plaster_sources
from app.database import get_db
from app.models import PdfCandidateSelection
from sqlalchemy import select
from test_a326_project_evidence import attach, pdf
from test_a335_plaster_poz_matching import (
    COARSE, FINE, _setup_pdf_pair, position,
)

COARSE_POSITION = position(
    "15.275.1116", "250 kg çimento dozlu harç ile kaba sıva yapılması",
)
FINE_POSITION = position(
    "15.275.1115", "350 kg çimento dozlu harçla tek kat ince sıva yapılması",
)
DEMOLITION_POSITION = position(
    "15.106.1104", "Her türlü iç sıva sökülmesi",
)


def _field(rows, key):
    return next(row for row in rows if row["key"] == key)


def test_excel_thickness_and_poz_dosage_are_not_project_evidence():
    fields = compare_plaster_sources(
        COARSE, COARSE_POSITION, [(1, "20 mm kaba siva; 8 mm ince siva.")]
    )
    thick = _field(fields, "thickness_mm")
    dose = _field(fields, "cement_dosage_kg")
    assert thick["excel"] == 20
    assert thick["project"] == "20"
    assert thick["status"] == "evidence_found"
    assert thick["evidence"][0]["page"] == 1
    assert dose["position"] == "250"
    assert dose["excel"] is None
    assert dose["project"] is None
    assert dose["status"] == "missing_project"
    assert _field(fields, "coverage")["status"] == "scope_review"


def test_dose_in_mixed_stage_paragraph_is_not_attributed_to_coarse_or_fine():
    blocks = [(3, "20 mm kaba siva; 8 mm ince siva; 250 kg cimento dozlu.")]
    for description, position_item in (
        (COARSE, COARSE_POSITION), (FINE, FINE_POSITION),
    ):
        fields = compare_plaster_sources(description, position_item, blocks)
        assert _field(fields, "cement_dosage_kg")["project"] is None
        assert _field(fields, "cement_dosage_kg")["status"] == "missing_project"


def test_explicit_stage_dosage_conflict_is_detected_and_cited():
    rows = compare_plaster_sources(
        COARSE, COARSE_POSITION,
        [(2, "20 mm kaba siva 350 kg cimento dozlu.")],
    )
    dosage = _field(rows, "cement_dosage_kg")
    assert dosage["position"] == "250"
    assert dosage["project"] == "350"
    assert dosage["status"] == "conflict"
    assert dosage["evidence"][0]["page"] == 2
    assert _field(rows, "thickness_mm")["status"] == "evidence_found"


def test_conflicting_project_thicknesses_are_not_silently_combined():
    rows = compare_plaster_sources(
        COARSE, COARSE_POSITION,
        [(2, "20 mm kaba siva"), (3, "30 mm kaba siva")],
    )
    thick = _field(rows, "thickness_mm")
    assert thick["status"] == "conflict"
    assert thick["project"] is None
    assert {i["page"] for i in thick["evidence"]} == {2, 3}


def test_readonly_api_facts_and_stale_old_poz_are_source_bound(
    client, auth, monkeypatch,
):
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch,
        positions=(COARSE_POSITION, FINE_POSITION, DEMOLITION_POSITION),
    )
    matched = client.get(
        f"/api/projects/{pid}/a318/imports/{iid}/suggestions", headers=auth,
    )
    assert matched.status_code == 200, matched.text
    first = matched.json()["rows"][0]
    item = first["work_item_id"]
    url = (
        f"/api/projects/{pid}/a338/imports/{iid}/items/{item}"
        f"/comparison?position_code={COARSE_POSITION.id}"
    )
    before = client.get(url, headers=auth)
    assert before.status_code == 200, before.text
    assert before.json()["document_state"] == "missing"
    assert before.json()["analysis_pdf_sha256"] == sha
    assert before.json()["cost_allowed"] is False

    attached = attach(
        client, auth, pid,
        pdf("20 mm kaba siva; 8 mm ince siva.",
            "20 mm kaba siva 250 kg cimento dozlu."),
    )
    assert attached.status_code == 201, attached.text
    read = client.get(url, headers=auth)
    assert read.status_code == 200, read.text
    data = read.json()
    assert data["document_sha256"] == attached.json()["sha256"]
    assert data["position_code"] == COARSE_POSITION.id
    assert data["position_pdf_page"] == 70
    assert data["engineering_approved"] is False
    assert data["cost_allowed"] is False
    dose = _field(data["source_checks"], "cement_dosage_kg")
    assert dose["project"] == "250"
    assert dose["status"] == "evidence_found"
    assert dose["evidence"][0]["page"] == 2

    saved = client.post(
        f"/api/projects/{pid}/a318/imports/{iid}/items/{item}/candidate",
        headers=auth,
        json={
            "position_code": COARSE_POSITION.id,
            "expected_revision_id": first["revision_id"],
            "expected_pdf_sha256": sha,
        },
    )
    assert saved.status_code == 200, saved.text
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        old = db.scalar(select(PdfCandidateSelection).where(
            PdfCandidateSelection.work_item_id == item,
        ))
        old.position_code = DEMOLITION_POSITION.id
        db.commit()
    finally:
        db.close()
    stale = client.get(url, headers=auth).json()
    assert stale["old_selection_stale_code"] == DEMOLITION_POSITION.id
    assert stale["candidate_blocked"] is False
    assert stale["engineering_approved"] is False
    assert stale["cost_allowed"] is False


def test_cross_tenant_and_missing_position_cannot_read_project_evidence(
    client, auth, monkeypatch,
):
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch, positions=(COARSE_POSITION,FINE_POSITION),
    )
    rows = client.get(
        f"/api/projects/{pid}/a318/imports/{iid}/suggestions",headers=auth,
    ).json()["rows"]
    item = rows[0]["work_item_id"]
    stem=f"/api/projects/{pid}/a338/imports/{iid}/items/{item}/comparison"
    assert client.get(stem+"?position_code=15.999.9999",headers=auth).status_code == 404
    other=client.post("/api/auth/register",json={
        "organization_name":"A338 Other","email":"a338-other@example.com",
        "password":"secure-pilot-password",
    })
    assert other.status_code == 201,other.text
    headers={"Authorization":"Bearer "+other.json()["access_token"]}
    assert client.get(stem+"?position_code=15.275.1116",headers=headers).status_code == 404
