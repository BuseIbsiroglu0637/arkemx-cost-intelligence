"""A3.35: forbid interchangeable coarse/fine plaster poz and double pricing."""
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from openpyxl import Workbook
from sqlalchemy import select

from app import a318_pdf_api
from app.a318_pdf_engine import PdfPosition
from app.a320_smart_matching import enrich_technical, find_pdf_candidates
from app.a335_plaster_matching import (
    plaster_binders, plaster_checks, plaster_dosages, plaster_stages,
)
from app.database import get_db
from app.models import PdfCandidateSelection
from app.technical import compare


def item(text, row=2):
    return SimpleNamespace(
        id=f"test-{row}", source_row=row, raw_description=text,
        quantity=Decimal("168.50"), normalized_unit="m²", review_required=False,
    )


def position(code, text, amount="350"):
    return PdfPosition(
        id=code, description=text, unit="m²", price=Decimal(amount),
        price_verified=True, pdf_page=70, scope="Poz PDF teknik kapsamı",
        ingredients=(),
    )


COARSE = "20 mm çimento esaslı kaba sıva"
FINE = "8 mm ince sıva uygulaması"
COMBINED = "20 mm kaba sıva ve 8 mm ince sıva birlikte yapılması"


def test_stage_recognition_is_specific_and_does_not_merge_layers():
    assert plaster_stages(COARSE) == {"kaba"}
    assert plaster_stages(FINE) == {"ince"}
    assert plaster_stages(COMBINED) == {"kaba", "ince"}
    assert plaster_stages("kaba ve ince sıva imalatı") == {"kaba", "ince"}
    assert plaster_stages("kaba/ince sıva imalatı") == {"kaba", "ince"}
    assert plaster_stages("kaba+ince sıva imalatı") == {"kaba", "ince"}
    assert plaster_stages("sıva katmanı kaba") == {"kaba"}
    assert plaster_stages("20 mm kaba sıvanması") == {"kaba"}
    assert plaster_stages("kaba kumla ince sıva") == {"ince"}
    assert plaster_stages("çimento harcı") == set()


def test_wrong_layer_and_combined_scope_are_hard_conflicts():
    mismatch, flags = plaster_checks(COARSE, FINE)
    assert "PLASTER_LAYER_MISMATCH" in mismatch
    assert plaster_checks(COARSE, COMBINED)[0] == [
        "PLASTER_COMBINED_SCOPE_MISMATCH"
    ]
    check = enrich_technical(
        COARSE, FINE,
        compare(COARSE, "m²", FINE, "m²"),
    )
    assert check["status"] == "blocked"
    assert "PLASTER_LAYER_MISMATCH" in check["blockers"]
    assert "THICKNESS_MM_MISMATCH" in check["blockers"]


def test_missing_layer_cannot_be_reported_technically_compatible():
    blockers, reviews = plaster_checks(
        COARSE, "20 mm çimento esaslı sıva yapılması",
    )
    assert not blockers
    assert "PLASTER_LAYER_UNVERIFIED" in reviews
    check = enrich_technical(
        COARSE, "20 mm çimento esaslı sıva yapılması",
        compare(COARSE, "m²", "20 mm çimento esaslı sıva yapılması", "m²"),
    )
    assert check["status"] == "review"
    assert "PLASTER_LAYER_UNVERIFIED" in check["review_flags"]


def test_binder_and_explicit_dosage_are_not_guessed():
    assert plaster_binders("250 kg çimento dozlu alçı sıva") == {"cimento", "alci"}
    assert plaster_dosages("250 kg çimento dozlu sıva") == {Decimal("250")}
    assert plaster_dosages("250 kg çimento ilavesi sıva") == set()
    blocker, _ = plaster_checks(
        "20 mm 250 kg çimento dozlu kaba sıva",
        "20 mm 350 kg çimento dozlu kaba sıva",
    )
    assert "PLASTER_CEMENT_DOSAGE_MISMATCH" in blocker
    binder, _ = plaster_checks(
        "20 mm çimento esaslı kaba sıva", "20 mm alçı esaslı kaba sıva",
    )
    assert "PLASTER_BINDER_MISMATCH" in binder
    _, flags = plaster_checks(
        "20 mm 250 kg çimento dozlu kaba sıva",
        "20 mm çimento esaslı kaba sıva",
    )
    assert "PLASTER_CEMENT_DOSAGE_UNVERIFIED" in flags


def test_candidate_retrieval_recovers_matching_stage_even_if_first_lexical_crowded():
    coarse = item(COARSE, 2)
    fine = item(FINE, 3)
    source = [
        position("15.999.2751", COMBINED),
        position("15.999.2752", "20 mm çimento esaslı ince sıva"),
        position("15.999.2753", "20 mm çimento esaslı kaba sıva uygulaması"),
        position("15.999.2754", "8 mm ince sıva uygulanması"),
        position("15.999.2755", "20 mm çimento esaslı sıva yapılması"),
    ]
    coarse_found = find_pdf_candidates(coarse, source)
    fine_found = find_pdf_candidates(fine, source)
    assert coarse_found[0]["position_id"] == "15.999.2753"
    assert fine_found[0]["position_id"] == "15.999.2754"
    assert coarse_found[0]["position_id"] != fine_found[0]["position_id"]
    inflected = position("15.999.2756", "20 mm çimento harcı ile kaba sıvanması")
    assert find_pdf_candidates(coarse, [inflected])[0]["position_id"] == inflected.id


def _setup_pdf_pair(client, auth, monkeypatch, *, positions=None):
    pdf_positions = positions or (
        position("15.999.2751", COMBINED),
        position("15.999.2752", "20 mm çimento esaslı kaba sıva yapılması"),
        position("15.999.2753", "8 mm ince sıva uygulanması"),
    )
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: pdf_positions)
    project = client.post("/api/projects", headers=auth, json={
        "name": "A3.35 plaster scope protection",
    })
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    wb = Workbook()
    sh = wb.active
    sh.append(["İmalat", "Miktar", "Birim"])
    sh.append([COARSE, 168.5, "m²"])
    sh.append([FINE, 168.5, "m²"])
    buf = BytesIO()
    wb.save(buf)
    imp = client.post(f"/api/projects/{pid}/imports", headers=auth,
                      files={"file": ("plaster.xlsx", buf.getvalue())})
    assert imp.status_code == 201, imp.text
    iid = imp.json()["id"]
    upload = client.post(
        f"/api/projects/{pid}/a318/source", headers=auth,
        data={"rights_confirmed": "true"},
        files={"file": ("2026.pdf", b"%PDF-" + b"A" * 1500, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    return pid, iid, upload.json()["sha256"]


def test_real_2026_mortar_title_identifies_both_plaster_stages():
    official = (
        "250/350 kg çimento dozlu kaba ve ince harçla "
        "serpme (çarpma) sıva yapılması"
    )
    assert plaster_stages(official) == {"kaba", "ince"}
    assert plaster_stages("Kaba ve ince harç ile sıva yapılması") == {
        "kaba", "ince",
    }
    assert "PLASTER_COMBINED_SCOPE_MISMATCH" in plaster_checks(
        COARSE, official, position_code="15.275.1114",
    )[0]
    assert "PLASTER_COMBINED_SCOPE_MISMATCH" in plaster_checks(
        FINE, official, position_code="15.275.1114",
    )[0]


def test_scope_and_known_official_combined_code_cannot_override_single_layer():
    scope = (
        "Kaba sıva yapılması, üzerine serpme (çarpma) sıva yapılması "
        "ve işçilik dahil 1 m² sıva fiyatı."
    )
    assert plaster_stages(scope) == {"kaba", "ince"}
    assert "PLASTER_COMBINED_SCOPE_MISMATCH" in plaster_checks(
        COARSE, "20 mm çimento esaslı kaba sıva", scope=scope,
    )[0]
    # Even if an imported title loses the word 'ince' during PDF parsing,
    # a confirmed 2026 combined poz code must not be passed as single-stage.
    assert "PLASTER_COMBINED_SCOPE_MISMATCH" in plaster_checks(
        COARSE, "20 mm çimento esaslı kaba sıva",
        position_code="15.275.1114",
    )[0]
    # Unrecognized/generic stage text is still review, not proof.
    blockers, pending = plaster_checks(COARSE, "20 mm çimento esaslı sıva")
    assert not blockers
    assert "PLASTER_LAYER_UNVERIFIED" in pending


def test_real_2026_poz_names_offer_only_separate_stage_candidates(
    client, auth, monkeypatch,
):
    official = (
        position("15.275.1114",
                 "250/350 kg çimento dozlu kaba ve ince harçla "
                 "serpme (çarpma) sıva yapılması"),
        position("15.275.1115",
                 "350 kg çimento dozlu harçla tek kat ince sıva yapılması"),
        position("15.275.1116",
                 "250 kg çimento dozlu harç ile kaba sıva yapılması"),
    )
    pid, iid, sha = _setup_pdf_pair(
        client, auth, monkeypatch, positions=official,
    )
    url = f"/api/projects/{pid}/a318/imports/{iid}"
    response = client.get(url + "/suggestions", headers=auth)
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["suggestions"][0]["code"] == "15.275.1116"
    assert rows[1]["suggestions"][0]["code"] == "15.275.1115"
    for row in rows:
        assert "15.275.1114" not in {
            entry["code"] for entry in row["suggestions"]
        }
        assert row.get("engineering_approved") in (None, False)
        denied = client.post(
            f"{url}/items/{row['work_item_id']}/candidate",
            headers=auth,
            json={
                "position_code": "15.275.1114",
                "expected_revision_id": row["revision_id"],
                "expected_pdf_sha256": sha,
            },
        )
        assert denied.status_code == 422
    # The correct separate-stage poz can be saved for further technical review.
    saved = client.post(
        f"{url}/items/{rows[0]['work_item_id']}/candidate",
        headers=auth,
        json={
            "position_code": "15.275.1116",
            "expected_revision_id": rows[0]["revision_id"],
            "expected_pdf_sha256": sha,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["cost_allowed"] is False

    # A legacy combined poz code is stale even when stored with a current SHA.
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    stored = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.work_item_id == rows[0]["work_item_id"],
    ))
    stored.position_code = "15.275.1114"
    db.commit()
    gen.close()
    after = client.get(url + "/suggestions", headers=auth).json()["rows"][0]
    assert after["saved_selection"]["stale"] is True
    assert after["saved_selection"]["stale_reason"] == "TECHNICAL_CONFLICT"


def test_api_keeps_two_plaster_rows_and_blocks_wrong_or_combined_poz(
    client, auth, monkeypatch,
):
    pid, iid, sha = _setup_pdf_pair(client, auth, monkeypatch)
    url = f"/api/projects/{pid}/a318/imports/{iid}"
    response = client.get(url + "/suggestions", headers=auth)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result.get("engineering_approved") in (None, False)
    assert result["cost_allowed"] is False
    assert result["approval_allowed"] is False
    rows = result["rows"]
    assert len(rows) == 2
    assert [r["source_row"] for r in rows] == [2, 3]
    assert rows[0]["related_excel_rows"] == [3]
    assert rows[1]["related_excel_rows"] == [2]
    assert rows[0]["suggestions"][0]["code"] == "15.999.2752"
    assert rows[1]["suggestions"][0]["code"] == "15.999.2753"
    assert all("15.999.2751" not in [c["code"] for c in r["suggestions"]]
               for r in rows)
    for index, blocked_code, valid_code in (
        (0, "15.999.2753", "15.999.2752"),
        (1, "15.999.2752", "15.999.2753"),
        (0, "15.999.2751", "15.999.2752"),
    ):
        row = rows[index]
        endpoint = f"{url}/items/{row['work_item_id']}/candidate"
        base = {
            "expected_revision_id": row["revision_id"],
            "expected_pdf_sha256": sha,
        }
        denied = client.post(endpoint, headers=auth, json={
            **base, "position_code": blocked_code,
        })
        assert denied.status_code == 422
        allowed = client.post(endpoint, headers=auth, json={
            **base, "position_code": valid_code,
        })
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["engineering_approved"] is False
        assert allowed.json()["cost_allowed"] is False


def test_existing_cross_stage_saved_poz_becomes_stale(client, auth, monkeypatch):
    pid, iid, sha = _setup_pdf_pair(client, auth, monkeypatch)
    url = f"/api/projects/{pid}/a318/imports/{iid}"
    rows = client.get(url + "/suggestions", headers=auth).json()["rows"]
    first = rows[0]
    endpoint = f"{url}/items/{first['work_item_id']}/candidate"
    assert client.post(endpoint, headers=auth, json={
        "position_code": "15.999.2752",
        "expected_revision_id": first["revision_id"], "expected_pdf_sha256": sha,
    }).status_code == 200

    # This simulates an old version having stored a wrong layer's code.
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    saved = db.scalar(select(PdfCandidateSelection).where(
        PdfCandidateSelection.work_item_id == first["work_item_id"],
    ))
    saved.position_code = "15.999.2753"
    db.commit()
    gen.close()
    refreshed = client.get(url + "/suggestions", headers=auth).json()
    invalid = refreshed["rows"][0]["saved_selection"]
    assert invalid["current"] is False
    assert invalid["stale"] is True
    assert invalid["stale_reason"] == "TECHNICAL_CONFLICT"
