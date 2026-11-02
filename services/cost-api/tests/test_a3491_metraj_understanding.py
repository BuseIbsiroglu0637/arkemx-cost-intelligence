"""A3.49.1 metraj understanding: source precision, not automated poz selection."""
from decimal import Decimal

from app.a349_metraj_understanding import describe_metraj
from test_a326_project_evidence import project_with_metraj
from test_api import register


def test_gazbeton_thickness_is_100mm_and_source_spans_are_exact():
    text = "10 cm gazbeton duvar yapılması malzeme ve işçilik dahil"
    row = describe_metraj(text, "m²", Decimal("84.25"))
    assert row["status"] == "structured_for_retrieval"
    assert row["material_family"] == "gazbeton"
    assert row["thicknesses_mm"] == ["100"]
    assert row["work_scope"] == "material_and_labor"
    assert row["quantity"] == "84.25"
    layer = row["layers"][0]
    evidence = layer["evidence"]
    assert evidence["quote"] == text[evidence["start"]:evidence["end"]]
    assert layer["thickness_mm"] == "100"
    assert row["match_selected"] is False and row["cost_allowed"] is False


def test_pvc_labor_only_material_supply_and_demolition_are_not_conflated():
    labor = describe_metraj(
        "PVC zemin kaplaması işçiliği (malzeme hariç)", "m²", Decimal(30),
    )
    material = describe_metraj(
        "PVC zemin kaplaması malzeme temini", "m²", Decimal(30),
    )
    demolition = describe_metraj(
        "Mevcut seramik zemin kaplaması sökülmesi", "m²", Decimal(30),
    )
    assert labor["material_family"] == "pvc"
    assert labor["work_scope"] == "labor_only"
    assert material["work_scope"] == "material_only"
    assert demolition["work_scope"] == "demolition"
    assert all(result["approval_allowed"] is False for result in (labor, material, demolition))


def test_2cm_cement_plaster_retains_binder_and_never_becomes_gypsum():
    cement = describe_metraj("2 cm çimento esaslı sıva yapılması", "m²", Decimal(17))
    gypsum = describe_metraj("2,5 cm alçı sıva yapılması", "m²", Decimal(17))
    assert cement["material_family"] == gypsum["material_family"] == "siva"
    assert cement["binder_materials"] == ["cimento"]
    assert gypsum["binder_materials"] == ["alci"]
    assert cement["thicknesses_mm"] == ["20"]
    assert gypsum["thicknesses_mm"] == ["25"]
    assert cement["match_selected"] is False


def test_multiple_explicit_works_are_not_assigned_one_thickness_or_poz():
    text = "10 cm gazbeton duvar, 2 cm sıva"
    result = describe_metraj(text, "m²", Decimal(12))
    assert result["material_family"] is None
    assert set(result["material_families"]) == {"gazbeton", "siva"}
    assert result["status"] == "multiple_works_for_review"
    assert "MULTIPLE_WORK_TYPES" in result["review_flags"]
    assert len(result["layers"]) == 2
    assert {row["work_type"]: row["thickness_mm"] for row in result["layers"]} == {
        "gazbeton_duvar": "100", "siva": "20",
    }
    for layer in result["layers"]:
        ev = layer["evidence"]
        assert text[ev["start"]:ev["end"]] == ev["quote"]


def test_tile_dimensions_and_grout_are_not_wall_thickness():
    text = "60×60 cm porselen seramik karo, 3 mm derz aralıklı"
    result = describe_metraj(text, "m²", Decimal(40))
    assert result["material_family"] == "seramik"
    assert result["technical_facts"]["dimensions"] == [[60, 60]]
    assert result["technical_facts"]["joint_width_mm"] == 3
    assert result["thicknesses_mm"] == []
    assert result["layers"] == []


def test_strength_density_are_technical_facts_not_thickness():
    result = describe_metraj(
        "10 cm gazbeton duvar, 2,50 N/mm² dayanım 400 kg/m³ yoğunluk",
        "m²", Decimal(40),
    )
    assert result["technical_facts"]["gazbeton_strength_n_mm2"] == 2.5
    assert result["technical_facts"]["gazbeton_density_kg_m3"] == 400
    assert result["thicknesses_mm"] == ["100"]


def test_unrecognized_family_and_missing_unit_require_review():
    row = describe_metraj(
        "Bilinmeyen karma imalat", None, None,
        input_review_required=True,
    )
    assert row["status"] == "needs_review"
    assert set(row["review_flags"]) >= {
        "MATERIAL_FAMILY_UNRECOGNIZED", "UNIT_MISSING",
        "QUANTITY_MISSING", "METRAJ_INPUT_REVIEW_REQUIRED",
    }
    assert row["match_selected"] is False


def test_tenant_scoped_batch_api_pagination_and_original_excel_identity(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    url = f"/api/projects/{pid}/a349/imports/{iid}/understanding"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=auth, params={"offset": 0, "limit": 1})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_rows"] == 2
    assert payload["returned"] == 1
    assert payload["has_more"] is True
    assert payload["source"]["project_id"] == pid
    assert payload["source"]["import_id"] == iid
    assert len(payload["source"]["excel_sha256"]) == 64
    assert payload["rows"][0]["work_item_id"] == ids[0]
    assert payload["rows"][0]["source_row"] == 2
    assert payload["rows"][0]["understanding"]["material_family"] == "gazbeton"
    assert payload["read_only"] is True
    assert payload["approval_allowed"] is False
    assert payload["catalog_matching_performed"] is False
    assert payload["cost_allowed"] is False
    assert response.headers["cache-control"] == "private, no-store"
    next_page = client.get(url, headers=auth, params={"offset": 1, "limit": 1}).json()
    assert next_page["rows"][0]["work_item_id"] == ids[1]
    assert next_page["has_more"] is False
    assert next_page["rows"][0]["understanding"]["material_family"] == "seramik"
    assert client.get(url, headers=auth, params={"limit": 101}).status_code == 422


def test_another_tenant_cannot_examine_private_metraj(client):
    owner = register(client, "A349 owner", "a349owner@example.com")
    other = register(client, "A349 other", "a349other@example.com")
    project, batch, _ = project_with_metraj(client, owner)
    url = f"/api/projects/{project}/a349/imports/{batch}/understanding"
    assert client.get(url, headers=other).status_code == 404
