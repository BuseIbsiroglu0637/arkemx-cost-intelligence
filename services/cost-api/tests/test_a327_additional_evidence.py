"""A3.27.3 — No cross-row guessing, explicit source pages, no approvals."""
from app.a326_project_evidence import _block_matches, _evidence_status
from app.a327_additional_evidence import conflicts_with_metraj
from test_a326_project_evidence import attach, evidence, pdf
from test_a327_engineer_handoff import readiness, six_row_project


def test_kaba_and_ince_plaster_are_distinct_even_in_one_pdf_block():
    blocks = [(4, "20 mm kaba siva; 8 mm ince siva.")]
    kaba = _block_matches("20 mm kaba siva", blocks)
    ince = _block_matches("8 mm ince siva", blocks)
    assert len(kaba) == 1
    assert len(ince) == 1
    assert kaba[0]["page"] == ince[0]["page"] == 4
    assert kaba[0]["facts"] == {
        "layer_type": "kaba", "layer_thickness_mm": 20.0
    }
    assert ince[0]["facts"] == {
        "layer_type": "ince", "layer_thickness_mm": 8.0
    }
    assert not conflicts_with_metraj("8 mm ince siva", ince)
    assert conflicts_with_metraj("10 mm ince siva", ince)
    assert _block_matches("siva", blocks) == []


def test_plaster_ambiguous_and_conflicting_thickness_stay_blocked():
    blocks = [(2, "20 mm kaba siva"), (3, "30 mm kaba siva")]
    matches = _block_matches("20 mm kaba siva", blocks)
    assert _evidence_status(matches) == "conflicting"
    assert conflicts_with_metraj("20 mm kaba siva", matches)
    assert not _block_matches("8 mm ince siva", blocks)
    assert not _block_matches("8 mm ince siva", [(1, "250 kg cimento")])
    # No dosage or m3-sand basis may be invented from bare quantities.
    assert "cement_dosage" not in matches[0]["facts"]


def test_concrete_class_must_be_explicit_and_wrong_class_is_conflict():
    valid = _block_matches(
        "C25/30 beton imalati",
        [(5, "C25/30 sinifinda beton dokulmesi.")],
    )
    assert valid == [{
        "page": 5, "quote": "C25/30 sinifinda beton dokulmesi.",
        "facts": {"concrete_class": "C25/30"},
    }]
    assert not conflicts_with_metraj("C25/30 beton", valid)
    assert conflicts_with_metraj("C30/37 beton", valid)
    assert _block_matches("C25/30 beton", [(1, "C25/30 celik kaynagi")]) == []
    assert _evidence_status(_block_matches(
        "C25/30 beton",
        [(1, "C25/30 beton"), (3, "C30/37 beton")],
    )) == "conflicting"


def test_paint_base_without_coats_is_not_guessed():
    matches = _block_matches(
        "ic cephe boya", [(6, "Ic cephe su bazli boya uygulanir.")],
    )
    assert len(matches) == 1
    assert matches[0]["facts"]["paint_base"] == "su bazli"
    assert matches[0]["facts"]["coat_count"] is None
    full = _block_matches(
        "ic cephe boya", [(6, "Ic cephe su bazli boya 2 kat uygulanir.")],
    )
    assert full[0]["facts"]["coat_count"] == 2
    assert conflicts_with_metraj("ic cephe solvent bazli boya", full)
    assert conflicts_with_metraj("ic cephe 3 kat su bazli boya", full)
    assert _evidence_status(_block_matches(
        "ic cephe boya", [(1, "su bazli boya 2 kat"),
                          (2, "solvent bazli boya 3 kat")],
    )) == "conflicting"
    assert _block_matches("ic cephe boya", [(6, "Boya ozellikleri projeye gore.")]) == []


def test_full_handoff_has_sourced_partial_evidence_for_four_more_works(client, auth):
    pid, iid = six_row_project(client, auth)
    doc = pdf(
        "10 cm gazbeton duvar: 2,50 N/mm2 400 kg/m3",
        "20 mm kaba siva; 8 mm ince siva.",
        "60x60 cm mat sirsiz rektifiyeli porselen seramik",
        "C25/30 beton uygulama notlari",
        "Ic cephe su bazli boya, kat sayisi belirtilmemis.",
    )
    assert attach(client, auth, pid, doc).status_code == 201
    response = readiness(client, auth, pid, iid)
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert len(rows) == 6
    assert [r["status"] for r in rows] == [
        "needs_candidate", "needs_candidate",
        "needs_candidate", "needs_candidate",
        "document_evidence_for_review", "document_evidence_for_review",
    ]
    assert rows[1]["evidence_page"] == rows[2]["evidence_page"] == 2
    assert rows[1]["evidence_facts"]["layer_thickness_mm"] == 20
    assert rows[2]["evidence_facts"]["layer_thickness_mm"] == 8
    assert rows[4]["evidence_facts"]["concrete_class"] == "C25/30"
    assert rows[5]["evidence_facts"]["paint_base"] == "su bazli"
    assert "coat_count" not in rows[5]["evidence_facts"]
    assert all(r["engineering_approved"] is False and
               r["cost_allowed"] is False for r in rows)


def test_contradictory_project_source_never_becomes_approved(client, auth):
    pid, iid = six_row_project(client, auth)
    assert attach(client, auth, pid, pdf(
        "C25/30 beton icin notlar.",
        "C30/37 beton icin notlar.",
        "20 mm kaba siva.",
        "30 mm kaba siva.",
        "Ic cephe su bazli boya.",
        "Ic cephe solvent bazli boya.",
    )).status_code == 201
    rows = readiness(client, auth, pid, iid).json()["rows"]
    assert rows[1]["status"] == "conflicting"
    assert rows[4]["status"] == "conflicting"
    assert rows[5]["status"] == "conflicting"
    assert all(r["engineering_approved"] is False and
               r["cost_allowed"] is False for r in rows)
