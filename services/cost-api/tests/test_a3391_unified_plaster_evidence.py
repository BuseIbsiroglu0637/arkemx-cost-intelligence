"""A3.39.1: identical, stage-specific facts in old and new PDF evidence readers."""
from app.a326_project_evidence import _block_matches, _evidence_status
from app.a338_plaster_evidence import compare_plaster_sources
from test_a326_project_evidence import attach, pdf
from test_a335_plaster_poz_matching import _setup_pdf_pair, position


COARSE = "20 mm cimento esasli kaba siva"
FINE = "8 mm ince siva"
COARSE_PDF = position(
    "15.275.1116", "250 kg cimento dozlu harc ile kaba siva yapilmasi",
)
FINE_PDF = position(
    "15.275.1115", "350 kg cimento dozlu harcla tek kat ince siva yapilmasi",
)


def _field(rows, key):
    return next(item for item in rows if item["key"] == key)


def test_material_qualified_thickness_is_found_by_both_readers():
    blocks = [(3, "20 mm cimento esasli kaba siva 250 kg cimento dozlu.")]
    old = _block_matches(COARSE, blocks)
    assert _evidence_status(old) == "found_for_review"
    assert {row["facts"].get("layer_thickness_mm") for row in old} == {20.0, None}
    assert {row["facts"].get("cement_dosage_kg") for row in old} == {250, None}
    assert all(row["page"] == 3 for row in old)
    new = compare_plaster_sources(COARSE, COARSE_PDF, blocks)
    assert _field(new, "thickness_mm")["project"] == "20"
    assert _field(new, "thickness_mm")["status"] == "evidence_found"
    assert _field(new, "cement_dosage_kg")["project"] == "250"
    assert _field(new, "cement_dosage_kg")["status"] == "evidence_found"


def test_mixed_stage_page_does_not_assign_ambiguous_cement_dose():
    blocks = [(1, "20 mm cimento esasli kaba siva uzerine 8 mm ince siva 250 kg cimento dozlu.")]
    for description, code in ((COARSE, COARSE_PDF), (FINE, FINE_PDF)):
        old = _block_matches(description, blocks)
        assert any(row["facts"].get("layer_thickness_mm") for row in old)
        assert not any(row["facts"].get("cement_dosage_kg") for row in old)
        new = compare_plaster_sources(description, code, blocks)
        assert _field(new, "cement_dosage_kg")["status"] == "missing_project"


def test_stage_specific_demo_appendix_is_identical_across_old_and_new_endpoints(
    client, auth, monkeypatch,
):
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch, positions=(COARSE_PDF, FINE_PDF),
    )
    source = pdf(
        "DEMO ornek sartname: Gercek proje belgesi degildir.",
        "20 mm cimento esasli kaba siva uzerine 8 mm ince siva.",
        "20 mm cimento esasli kaba siva 250 kg cimento dozlu.",
        "8 mm ince siva 350 kg cimento dozlu.",
    )
    result = attach(client, auth, pid, source)
    assert result.status_code == 201, result.text
    document_sha = result.json()["sha256"]
    rows = client.get(
        f"/api/projects/{pid}/a318/imports/{iid}/suggestions", headers=auth,
    ).json()["rows"]
    for idx, candidate, expected_page, thickness, dosage in (
        (0, COARSE_PDF, 3, 20, 250),
        (1, FINE_PDF, 4, 8, 350),
    ):
        item = rows[idx]["work_item_id"]
        old = client.get(
            f"/api/projects/{pid}/a326/imports/{iid}/items/{item}/evidence",
            headers=auth,
        )
        assert old.status_code == 200, old.text
        older = old.json()
        assert older["status"] == "found_for_review"
        assert older["source_sha256"] == document_sha
        assert any(
            record["page"] == expected_page and
            record["facts"].get("layer_thickness_mm") == thickness
            for record in older["evidence"]
        )
        assert any(
            record["page"] == expected_page and
            record["facts"].get("cement_dosage_kg") == dosage
            for record in older["evidence"]
        )
        new = client.get(
            f"/api/projects/{pid}/a338/imports/{iid}/items/{item}"
            f"/comparison?position_code={candidate.id}",
            headers=auth,
        )
        assert new.status_code == 200, new.text
        data = new.json()
        assert data["document_sha256"] == document_sha
        assert data["analysis_pdf_sha256"] == sha
        assert data["engineering_approved"] is False
        assert data["cost_allowed"] is False
        info = data["source_checks"]
        th = _field(info, "thickness_mm")
        dose = _field(info, "cement_dosage_kg")
        assert th["project"] == str(thickness)
        assert dose["project"] == str(dosage)
        assert th["status"] == "evidence_found"
        assert dose["status"] == "evidence_found"
        assert any(e["page"] == expected_page for e in th["evidence"])
        assert any(e["page"] == expected_page for e in dose["evidence"])


def test_numeric_conflict_remains_visible_and_not_approved():
    blocks = [
        (2, "20 mm cimento esasli kaba siva 250 kg cimento dozlu."),
        (3, "30 mm cimento esasli kaba siva 350 kg cimento dozlu."),
    ]
    old = _block_matches(COARSE, blocks)
    assert _evidence_status(old) == "conflicting"
    new = compare_plaster_sources(COARSE, COARSE_PDF, blocks)
    assert _field(new, "thickness_mm")["status"] == "conflict"
    assert _field(new, "cement_dosage_kg")["status"] == "conflict"
