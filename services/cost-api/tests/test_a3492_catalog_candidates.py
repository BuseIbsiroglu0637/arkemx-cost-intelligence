"""A3.49.2: source-verified catalog search with technical contradiction guards."""
from decimal import Decimal

from app.a3492_catalog_candidates import discover_candidates, _ranked_prefilter
from test_a326_project_evidence import project_with_metraj
from test_a348_official_price_list import source_pdf
from test_api import register


def row(code, description, *, unit="m²", kind="insaat", price="723.73", page=9):
    return {
        "code": code, "description": description, "unit": unit,
        "kind": kind, "unit_price": price, "price_status": "cell_extracted" if price else "unpriced",
        "pdf_page": page, "parent_description": None, "cost_allowed": False,
    }


def catalog(*items):
    return {
        "edition_date": "01.01.2026", "source_sha256": "a" * 64,
        "records": list(items), "read_only": True,
        "approval_allowed": False, "cost_allowed": False,
    }


def test_gazbeton_retrieves_exact_thickness_and_excludes_wrong_thickness():
    source = catalog(
        row("15.225.1004", "10 cm gazbeton duvar yapılması malzeme ve işçilik dahil"),
        row("15.225.1005", "15 cm gazbeton duvar yapılması malzeme ve işçilik dahil"),
        row("15.225.1006", "10 cm tuğla duvar yapılması malzeme ve işçilik dahil"),
    )
    analysis = {"records": [{"code": "15.225.1004"}], "source_sha256": "b" * 64}
    data = discover_candidates(
        "10 cm gazbeton duvar yapılması malzeme ve işçilik dahil",
        "m²", Decimal("84.25"), source, analysis,
    )
    assert data["status"] == "candidates_for_engineer_review"
    assert data["candidates"][0]["code"] == "15.225.1004"
    assert data["candidates"][0]["analysis_cilt1_linked"] is True
    assert data["candidates"][0]["pdf_source_sha256"] == "a" * 64
    assert all(x["code"] != "15.225.1005" for x in data["candidates"])
    assert all(x["code"] != "15.225.1006" for x in data["candidates"])
    blocked = {item["code"]: item["blockers"] for item in data["blocked_examples"]}
    assert "THICKNESS_MM_MISMATCH" in blocked["15.225.1005"]
    assert "MATERIAL_FAMILY_MISMATCH" in blocked["15.225.1006"]
    assert data["approval_allowed"] is False and data["cost_allowed"] is False
    assert data["candidates"][0]["technical_compliance_verified"] is False


def test_cement_plaster_does_not_recommend_gypsum_plaster_as_valid():
    data = discover_candidates(
        "2 cm çimento esaslı sıva yapılması", "m²", Decimal(10),
        catalog(
            row("15.275.1111", "2 cm çimento esaslı sıva yapılması"),
            row("15.275.1112", "2,5 cm alçı sıva yapılması"),
        ),
    )
    assert any(c["code"] == "15.275.1111" for c in data["candidates"])
    assert all(c["code"] != "15.275.1112" for c in data["candidates"])
    gypsum = next(c for c in data["blocked_examples"] if c["code"] == "15.275.1112")
    assert "PLASTER_BINDER_MISMATCH" in gypsum["blockers"]


def test_ceramic_size_60x60_rejects_30x60_even_with_same_material():
    data = discover_candidates(
        "60x60 cm porselen seramik zemin kaplaması", "m²", Decimal(10),
        catalog(
            row("15.300.1001", "60x60 cm porselen seramik zemin kaplaması"),
            row("15.300.1002", "30x60 cm porselen seramik zemin kaplaması"),
        ),
    )
    assert [x["code"] for x in data["candidates"]] == ["15.300.1001"]
    other = next(c for c in data["blocked_examples"] if c["code"] == "15.300.1002")
    assert "DIMENSIONS_MISMATCH" in other["blockers"]


def test_labor_only_material_only_and_demolition_never_turn_into_combined_work():
    data = discover_candidates(
        "PVC zemin kaplaması işçiliği (malzeme hariç)", "m²", Decimal(20),
        catalog(
            row("15.500.1001", "PVC zemin kaplaması malzeme temini"),
            row("15.500.1002", "PVC zemin kaplaması işçiliği (malzeme hariç)"),
            row("15.500.1003", "PVC zemin kaplaması yapılması malzeme ve işçilik dahil"),
        ),
    )
    assert [x["code"] for x in data["candidates"]] == ["15.500.1002"]
    assert {x["code"] for x in data["blocked_examples"]} == {
        "15.500.1001", "15.500.1003",
    }
    demolition = discover_candidates(
        "Mevcut seramik zemin kaplaması sökülmesi", "m²", Decimal(20),
        catalog(
            row("15.601.1001", "Mevcut seramik zemin kaplaması sökülmesi"),
            row("15.601.1002", "Seramik zemin kaplaması yapılması"),
        ),
    )
    assert [x["code"] for x in demolition["candidates"]] == ["15.601.1001"]
    assert any("WORK_SCOPE_DEMOLITION_MISMATCH" in c["blockers"]
               for c in demolition["blocked_examples"])


def test_two_works_one_excel_row_is_never_forced_into_one_poz():
    data = discover_candidates(
        "10 cm gazbeton duvar, 2 cm sıva", "m²", Decimal(10),
        catalog(row("15.225.1004", "10 cm gazbeton duvar")),
    )
    assert data["status"] == "needs_input_review"
    assert data["candidate_count"] == 0
    assert data["candidates"] == []
    assert data["scanned_count"] == 0


def test_unit_mismatch_blocked_and_missing_price_stays_null():
    data = discover_candidates(
        "10 cm gazbeton duvar", "m²", Decimal(10),
        catalog(
            row("15.225.1004", "10 cm gazbeton duvar", unit="m³", price="723.73"),
            row("15.225.1005", "10 cm gazbeton duvar", unit="m²", price=None),
        ),
    )
    assert [x["code"] for x in data["candidates"]] == ["15.225.1005"]
    assert data["candidates"][0]["unit_price"] is None
    assert "PDF_PRICE_UNAVAILABLE" in data["candidates"][0]["review_flags"]
    assert "UNIT_MISMATCH" in data["blocked_examples"][0]["blockers"]


def test_out_of_catalog_code_never_invented_or_assigned():
    source = catalog(row("15.225.1004", "Gazbeton duvar 10 cm"))
    data = discover_candidates(
        "99.999.9999 bilinmeyen ürün", "m²", Decimal(10), source,
    )
    assert all(c["code"] in {"15.225.1004"} for c in data["candidates"])
    assert data["approval_allowed"] is False
    assert data["cost_allowed"] is False


def test_exact_code_ref_does_not_override_unit_contradiction():
    source = catalog(row("15.225.1004", "10 cm gazbeton duvar", unit="m³"))
    data = discover_candidates("15.225.1004 10 cm gazbeton duvar", "m²", Decimal(20), source)
    assert data["candidates"] == []
    assert data["blocked_examples"][0]["code"] == "15.225.1004"
    assert "UNIT_MISMATCH" in data["blocked_examples"][0]["blockers"]


def test_api_requires_tenant_and_uses_2026_pdf_source_without_m5_writes(client, auth):
    pid, iid, item_ids = project_with_metraj(client, auth)
    url = f"/api/projects/{pid}/a349/imports/{iid}/items/{item_ids[0]}/candidates"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth).status_code == 409  # no price list
    uploaded = client.post(
        "/api/a348/catalog/source", headers=auth,
        files={"file": ("source.pdf", source_pdf())},
    )
    assert uploaded.status_code == 201, uploaded.text
    response = client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["read_only"] is True
    assert result["catalog_matching_performed"] is True
    assert result["candidate_selected"] is False
    assert result["approval_allowed"] is False and result["cost_allowed"] is False
    assert result["catalog"]["edition_date"] == "01.01.2026"
    assert result["catalog"]["position_count"] == 3
    assert result["excel"]["source_row"] == 2
    assert result["excel"]["work_item_id"] == item_ids[0]
    # PDF fixture says "m", while the Excel is m²: never bypass the unit gate.
    assert result["candidates"] == []
    assert any("UNIT_MISMATCH" in x["blockers"] for x in result["blocked_examples"])
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get("/api/projects", headers=auth).status_code == 200


def test_api_rejects_other_organizations_work_items(client):
    owner = register(client, "A3492 owner", "a3492owner@example.com")
    outsider = register(client, "A3492 other", "a3492other@example.com")
    pid, iid, ids = project_with_metraj(client, owner)
    url = f"/api/projects/{pid}/a349/imports/{iid}/items/{ids[0]}/candidates"
    assert client.get(url, headers=outsider).status_code == 404


def test_prefilter_is_deterministic_and_bounded():
    pool = [row(f"15.225.{i:04d}", "10 cm gazbeton duvar imalatı") for i in range(300)]
    matches = _ranked_prefilter("10 cm gazbeton duvar", pool)
    assert len(matches) == 180
    assert matches[0][1]["code"] == "15.225.0000"


def test_unknown_excel_material_does_not_offer_thin_cement_coatings_from_generic_words():
    """Regression: screenshot showed 1.5 / 2 / 3 mm coating codes with no source material."""
    source = catalog(
        row("15.540.1427", "Beton, sıva ve benzeri yüzeylere 1,5 mm çimento esaslı kaplama yapılması", price="465.38"),
        row("15.540.1428", "Beton, sıva ve benzeri yüzeylere 2 mm çimento esaslı kaplama yapılması", price="469.15"),
        row("15.540.1429", "Beton, sıva ve benzeri yüzeylere 3 mm çimento esaslı kaplama yapılması", price="543.74"),
    )
    # Neither this source nor a code number specifies an actual material family.
    data = discover_candidates(
        "Özel yüzey hazırlanması, uygulama ve kaplama işleri",
        "m²", Decimal("25"), source,
    )
    assert data["understanding"]["material_families"] == []
    assert data["status"] == "needs_input_review"
    assert data["candidates"] == []
    assert data["candidate_count"] == 0
    assert data["scanned_count"] == 0
    assert "güvenilir biçimde" in data["reason"]
    assert data["approval_allowed"] is False and data["cost_allowed"] is False


def test_unknown_work_with_explicit_poz_code_still_needs_material_review():
    source = catalog(
        row("15.540.1428", "2 mm çimento esaslı kaplama yapılması"),
    )
    data = discover_candidates("15.540.1428 özel kaplama işi", "m²", Decimal("5"), source)
    assert data["status"] == "needs_input_review"
    assert data["candidates"] == []
    assert "MATERIAL_FAMILY_UNRECOGNIZED" in data["understanding"]["review_flags"]


def test_recognized_gazbeton_can_still_retrieve_verified_source_poz():
    source = catalog(row("15.225.1004", "10 cm gazbeton duvar yapılması"))
    data = discover_candidates("10 cm gazbeton duvar", "m²", Decimal("20"), source)
    assert data["candidates"][0]["code"] == "15.225.1004"
    assert data["candidates"][0]["technical_compliance_verified"] is False
