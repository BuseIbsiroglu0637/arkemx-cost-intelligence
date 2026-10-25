"""M2 regression tests. All catalog codes are fictional DEMO IDs."""
from io import BytesIO
from types import SimpleNamespace
from openpyxl import Workbook
from app.matching import evaluate, find_candidates, similarity


def item(description, unit="m²", quantity=12, review=False):
    return SimpleNamespace(
        id="item", raw_description=description,
        normalized_unit=unit, quantity=quantity,
        review_required=review
    )


def pos(code, description, unit="m²"):
    return SimpleNamespace(id=code, code=code, description=description, unit=unit)


def build_xlsx(rows):
    w = Workbook()
    s = w.active
    s.append(["İmalat Açıklaması", "Miktar", "Birim"])
    for row in rows:
        s.append(row)
    buffer = BytesIO()
    w.save(buffer)
    return buffer.getvalue()


def auth(client, name, email):
    res = client.post("/api/auth/register", json={
        "organization_name": name, "email": email,
        "password": "long-test-password-123"
    })
    assert res.status_code == 201, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def create_project(client, headers):
    res = client.post("/api/projects", headers=headers, json={"name": "M2 Deneme Projesi"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def create_import(client, headers, pid, rows):
    res = client.post(f"/api/projects/{pid}/imports",
                      headers=headers, files={"file": ("fixture.xlsx", build_xlsx(rows))})
    assert res.status_code == 201, res.text
    return res.json()


def test_lexical_candidate_from_supplied_catalog_only():
    work = item("Porselen seramik kaplama 60x60")
    catalog = [
        pos("DEMO-SER", "60 x 60 porselen seramik zemin kaplaması"),
        pos("DEMO-BET", "Hazır beton dökümü", "m³"),
    ]
    result = find_candidates(work, catalog)
    assert len(result) == 1
    assert result[0]["position_id"] == "DEMO-SER"
    assert result[0]["approvable"] is True
    assert 0 < result[0]["similarity"] <= 1


def test_unit_mismatch_never_approved():
    result = evaluate(item("Gazbeton duvar 10 cm", "m²"), pos("DEMO-GAZ", "10 cm gazbeton duvar", "m³"))
    assert result is not None
    assert "UNIT_MISMATCH" in result["warnings"]
    assert not result["approvable"]


def test_thickness_and_dimension_constraints():
    bad_thickness = evaluate(item("Gazbeton duvar 10 cm"), pos("X", "Gazbeton duvar 15 cm"))
    assert "THICKNESS_MISMATCH" in bad_thickness["warnings"]
    bad_size = evaluate(item("Seramik 60x60"), pos("Y", "Seramik 30x60"))
    assert "DIMENSION_MISMATCH" in bad_size["warnings"]
    missing_size = evaluate(item("Seramik 60x60"), pos("Z", "Seramik duvar kaplaması"))
    assert "DIMENSION_MISMATCH" in missing_size["warnings"]


def test_unknown_quantity_blocks_approval():
    result = evaluate(item("10 cm gazbeton duvar", quantity=None, review=True),
                      pos("DEMO-GAZ", "Gazbeton duvar 10 cm"))
    assert result is not None
    assert not result["approvable"]
    assert "METRAJ_REVIEW_REQUIRED" in result["warnings"]


def test_unrelated_item_has_no_candidate():
    results = find_candidates(item("Porselen seramik kaplama 60x60"),
                              [pos("DEMO-BOYA", "Duvar boyası uygulanması")])
    assert results == []


def test_m2_end_to_end_and_immutable_decision(client):
    headers = auth(client, "Birinci Ofis", "m2a@example.com")
    project = create_project(client, headers)
    rows = [
        ["Porselen seramik kaplama 60x60", "245,50", "m2"],
        ["Gazbeton duvar 10 cm", "1.234", "m2"],
        ["Hazır beton dökümü", "10,50", "m3"],
        ["Kapı montajı", 4, "adet"],
        ["Boya işleri", 15, "kutu"],
    ]
    create_import(client, headers, project, rows)
    demo = client.post("/api/m2/demo-catalog", headers=headers)
    assert demo.status_code == 201, demo.text
    assert demo.json()["synthetic"] is True
    again = client.post("/api/m2/demo-catalog", headers=headers)
    assert again.json()["version_id"] == demo.json()["version_id"]
    run = client.post(f"/api/projects/{project}/m2/run", headers=headers,
                      json={"use_local_ollama": False})
    assert run.status_code == 201, run.text
    assert run.json()["row_count"] == 5
    assert run.json()["candidate_count"] >= 3
    latest = client.get(f"/api/projects/{project}/m2/latest", headers=headers)
    assert latest.status_code == 200, latest.text
    data = latest.json()
    assert len(data["items"]) == 5
    assert data["run"]["synthetic"] is True
    assert not data["run"]["scores_are_probabilities"]
    first = data["items"][0]["candidates"][0]
    assert first["code"].startswith("DEMO-")
    assert first["approvable"]
    approval = client.post(f"/api/projects/{project}/m2/decisions", headers=headers,
                           json={"run_id": run.json()["id"], "candidate_id": first["id"],
                                 "action": "approve"})
    assert approval.status_code == 201, approval.text
    latest_again = client.get(f"/api/projects/{project}/m2/latest", headers=headers).json()
    assert latest_again["items"][0]["decision"]["action"] == "approve"
    blocked = data["items"][1]["candidates"][0]
    assert not blocked["approvable"]
    denied = client.post(f"/api/projects/{project}/m2/decisions", headers=headers,
                         json={"run_id": run.json()["id"], "candidate_id": blocked["id"],
                               "action": "approve"})
    assert denied.status_code == 409
    # A new import must not alter historical match run's original work-item set.
    create_import(client, headers, project, [["Yeni iç kapı montajı", 3, "adet"]])
    historical = client.get(f"/api/projects/{project}/m2/latest", headers=headers).json()
    assert len(historical["items"]) == 5
    assert historical["items"][0]["decision"]["action"] == "approve"


def test_m2_tenant_isolation_and_not_yet_production_licensed(client):
    first = auth(client, "Firma A", "m2owner@example.com")
    second = auth(client, "Firma B", "m2other@example.com")
    project = create_project(client, first)
    create_import(client, first, project, [["Porselen seramik 60x60", 20, "m2"]])
    assert client.post(f"/api/projects/{project}/m2/run", headers=first, json={}).status_code == 409
    # Admin attestation of an arbitrary third-party source does not allow M2 matching.
    arbitrary = client.post("/api/catalog/sources", headers=first,
                            json={"institution": "OTHER-LICENSE-UNCHECKED"}).json()
    client.post(f"/api/catalog/sources/{arbitrary['id']}/verify", headers=first,
                json={"license_evidence": "Declared consent by local admin",
                      "permission_scope": "Pilot matching"})
    assert client.post(f"/api/projects/{project}/m2/run", headers=first, json={}).status_code == 409
    client.post("/api/m2/demo-catalog", headers=first)
    run = client.post(f"/api/projects/{project}/m2/run", headers=first, json={}).json()
    assert client.get(f"/api/projects/{project}/m2/latest", headers=second).status_code == 404
    assert client.post(f"/api/projects/{project}/m2/run", headers=second, json={}).status_code == 404
    first_latest = client.get(f"/api/projects/{project}/m2/latest", headers=first).json()
    candidate = first_latest["items"][0]["candidates"][0]
    assert client.post(f"/api/projects/{project}/m2/decisions", headers=second,
                       json={"run_id": run["id"], "candidate_id": candidate["id"],
                             "action": "approve"}).status_code == 404
    assert client.get("/api/catalog/sources", headers=second).json() == []


def test_m2_limits(client):
    headers = auth(client, "Limit", "m2limit@example.com")
    project = create_project(client, headers)
    create_import(client, headers, project, [["Kapı montajı", 1, "adet"]] * 101)
    client.post("/api/m2/demo-catalog", headers=headers)
    res = client.post(f"/api/projects/{project}/m2/run", headers=headers, json={})
    assert res.status_code == 422


def test_source_requires_explicit_dimensions_for_specific_catalog():
    result = evaluate(item("Gazbeton duvar", unit="m²"),
                      pos("DEMO-GAZ", "Gazbeton duvar 10 cm", unit="m²"))
    assert result is not None
    assert "THICKNESS_NOT_SPECIFIED_IN_METRAJ" in result["warnings"]
    assert result["approvable"] is False
