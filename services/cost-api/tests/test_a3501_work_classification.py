"""A3.50.1: same work-object taxonomy for Excel and PDF; no fake approvals."""
from decimal import Decimal

from app.a350_work_taxonomy import classify_work, compare_work_classes
from app.a3492_catalog_candidates import discover_candidates
from test_a3492_catalog_candidates import catalog, row
from test_a326_project_evidence import project_with_metraj
from test_a348_official_price_list import source_pdf
from test_api import register


def key(text):
    return classify_work(text)["class_key"]


def test_gazbeton_and_cement_vs_gypsum_plaster_classes():
    assert key("10 cm gazbeton bölme duvar yapılması") == "gazbeton_wall"
    assert key("10 cm tuğla duvar yapılması") == "brick_wall"
    assert key("2 cm çimento esaslı sıva yapılması") == "plaster_cement"
    assert key("2,5 cm alçı sıva yapılması") == "plaster_gypsum"
    assert key("10 cm gazbeton duvar ve 2 cm sıva") == "multiple"


def test_seramik_salmastra_musluk_not_ceramic_surface():
    tap = classify_work('3/4" seramik salmastralı Osmanlı musluğu rozet dahil')
    finish = classify_work("60x60 cm seramik karo zemin kaplaması")
    assert tap["class_key"] == "plumbing_tap"
    assert tap["trade"] == "mekanik_tesisat"
    assert finish["class_key"] == "ceramic_surface"
    assert compare_work_classes(finish, tap) == ["WORK_CLASS_MISMATCH"]
    assert finish["auto_match_allowed"] is False


def test_pvc_work_object_is_a_category_not_a_shared_word():
    assert key("PVC zemin kaplaması yapılması") == "pvc_floor"
    assert key("PVC den mamul 7 cm extrude profil") == "pvc_profile"
    assert key("PVC pis su borusu montajı") == "pvc_pipework"
    assert key("PVC pencere doğraması yapılması") == "pvc_joinery"


def test_coating_on_concrete_and_plaster_substrates_not_plaster_construction():
    text = "Beton, sıva ve benzeri yüzeylere 2 mm kalınlıkta çimento esaslı kaplama yapılması"
    assert key(text) == "cement_surface_coating"
    assert key("Sıva yapılması 2 cm çimento esaslı") == "plaster_cement"


def test_generic_brands_and_empty_descriptions_remain_unclassified():
    for text in ("Tulip Block (Diyarbakır)", "Silver Black (Afyon)", ""):
        result = classify_work(text, catalog_kind="rayic")
        assert result["class_key"] == "unknown"
        assert result["status"] == "unclassified"
        assert result["source_role"] == "catalog_rayic"
        assert result["evidence_terms"] == []
        assert result["auto_match_allowed"] is False
        assert result["technical_approved"] is False


def test_technical_work_class_blocks_unrelated_pdf_candidates_before_ranking():
    entries = catalog(
        row("10.240.1760", "Tulip Block", kind="rayic"),
        row("10.480.5131", "PVC extrude profil", kind="rayic"),
        row("15.600.1001", "PVC zemin kaplaması yapılması", kind="insaat"),
        row("25.130.1115", "Seramik salmastralı Osmanlı musluğu", kind="mekanik", unit="m²"),
    )
    result = discover_candidates("PVC zemin kaplaması yapılması", "m²", Decimal(100), entries)
    assert result["version"] == "a3501-class-first-v1"
    assert result["source_work_class"]["class_key"] == "pvc_floor"
    assert [c["code"] for c in result["candidates"]] == ["15.600.1001"]
    blocked = {c["code"]: c for c in result["blocked_examples"]}
    assert "10.240.1760" not in [c["code"] for c in result["candidates"]]
    assert "WORK_CLASS_MISMATCH" in blocked["10.480.5131"]["blockers"]


def test_multiwork_excel_cannot_generate_a_single_candidate():
    result = discover_candidates(
        "10 cm gazbeton duvar, 2 cm sıva",
        "m²", Decimal(10),
        catalog(row("15.225.1004", "10 cm gazbeton duvar")),
    )
    assert result["source_work_class"]["status"] == "multiple"
    assert result["candidates"] == []
    assert result["scanned_count"] == 0


def test_classification_api_source_provenance_real_rows_and_no_writes(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    url = f"/api/projects/{pid}/a350/imports/{iid}/classification"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=auth, params={"limit": 1})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["read_only"] and not data["approval_allowed"]
    assert not data["matching_performed"] and not data["cost_allowed"]
    assert data["version"] == "a3501-work-object-v1"
    assert data["total_rows"] == 2
    assert data["source"]["import_id"] == iid
    assert len(data["source"]["excel_sha256"]) == 64
    assert data["rows"][0]["source_row"] == 2
    assert data["rows"][0]["work_item_id"] == ids[0]
    assert data["rows"][0]["work_class"]["class_key"] == "gazbeton_wall"
    assert data["summary"]["classified_count"] + data["summary"]["review_count"] == 2
    assert data["has_more"] is True
    assert client.get(url, headers=auth, params={"limit": 51}).status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get(url, headers=auth, params={"offset": 1}).json()["rows"][0]["work_item_id"] == ids[1]


def test_classification_catalog_requires_installed_source_and_reports_all_rows(client, auth):
    endpoint = "/api/a350/catalog/classification"
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=auth).status_code == 409
    uploaded = client.post(
        "/api/a348/catalog/source", headers=auth,
        files={"file": ("2026.pdf", source_pdf())},
    )
    assert uploaded.status_code == 201, uploaded.text
    response = client.get(endpoint, headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_records"] == 3
    assert data["source"]["edition_date"] == "01.01.2026"
    assert data["summary"]["classified_count"] + data["summary"]["review_count"] == 3
    assert data["read_only"] is True
    assert data["matching_performed"] is False
    assert data["approval_allowed"] is False and data["cost_allowed"] is False
    assert response.headers["cache-control"] == "private, no-store"


def test_other_organization_cannot_read_excel_classification(client):
    owner = register(client, "Taxonomy owner", "taxonomyowner@example.com")
    other = register(client, "Taxonomy other", "taxonomyother@example.com")
    pid, iid, _ = project_with_metraj(client, owner)
    endpoint = f"/api/projects/{pid}/a350/imports/{iid}/classification"
    assert client.get(endpoint, headers=other).status_code == 404
