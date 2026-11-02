"""A3.47: source-bound technical facts without implied engineering approval."""
from types import SimpleNamespace

from app.a347_spec_completion import _summarize_facts, _safe_result
from test_a326_project_evidence import project_with_metraj, attach, pdf
from test_api import register


def _fact(rows, key):
    return next(row for row in rows if row["key"] == key)


def test_gazbeton_facts_autofill_with_real_page_citation_and_no_approval(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    document = pdf(
        "Genel bilgiler: diger isler.",
        "Gazbeton 10 cm duvar: 2,50 N/mm2 dayanim ve 400 kg/m3 yogunluk.",
    )
    attachment = attach(client, auth, pid, document)
    assert attachment.status_code == 201, attachment.text
    url = f"/api/projects/{pid}/a347/imports/{iid}/items/{ids[0]}/completion"
    answer = client.get(url, headers=auth)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["read_only"] is True
    assert data["approval_allowed"] is False
    assert data["engineering_approved"] is False
    assert data["cost_allowed"] is False
    assert data["document_sha256"] == attachment.json()["sha256"]
    strength = _fact(data["facts"], "gazbeton_strength_n_mm2")
    density = _fact(data["facts"], "gazbeton_density_kg_m3")
    assert strength["value"] == 2.5 and strength["state"] == "found_for_review"
    assert density["value"] == 400 and density["state"] == "found_for_review"
    assert strength["evidence"][0]["page"] == 2
    assert data["selected_position_code"] is None
    assert answer.headers["cache-control"] == "private, no-store"


def test_conflicting_spec_facts_are_never_silently_filled(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    document = pdf(
        "Gazbeton 10 cm duvar: 2,50 N/mm2 dayanim ve 400 kg/m3 yogunluk.",
        "Gazbeton 10 cm duvar: 3,50 N/mm2 dayanim ve 400 kg/m3 yogunluk.",
    )
    assert attach(client, auth, pid, document).status_code == 201
    url = f"/api/projects/{pid}/a347/imports/{iid}/items/{ids[0]}/completion"
    data = client.get(url, headers=auth).json()
    assert _fact(data["facts"], "gazbeton_strength_n_mm2")["state"] == "conflict"
    assert data["status"] == "technical_conflict"
    assert data["engineering_approved"] is False and data["cost_allowed"] is False


def test_position_and_excel_disagreement_stays_conflict():
    row = [{"page": 3, "quote": "10 cm gazbeton duvar, 2.5 N/mm2 400 kg/m3",
            "facts": {"gazbeton_strength_n_mm2": 2.5,
                      "gazbeton_density_kg_m3": 400}}]
    different = SimpleNamespace(description="10 cm gazbeton duvar 3.5 N/mm2 500 kg/m3")
    results = _summarize_facts("10 cm gazbeton duvar", row, different)
    assert _fact(results, "gazbeton_strength_n_mm2")["state"] == "conflict"
    assert _fact(results, "gazbeton_density_kg_m3")["state"] == "conflict"


def test_no_document_and_unrelated_document_keep_missing_explicit(client, auth):
    pid, iid, ids = project_with_metraj(client, auth)
    url = f"/api/projects/{pid}/a347/imports/{iid}/items/{ids[0]}/completion"
    missing = client.get(url, headers=auth).json()
    assert missing["document_status"] == "no_document"
    assert missing["cost_allowed"] is False
    assert missing["missing"]
    assert attach(client, auth, pid, pdf("Mermer kaplama baska is kalemi.")).status_code == 201
    unrelated = client.get(url, headers=auth).json()
    assert unrelated["document_status"] == "not_found"
    assert _fact(unrelated["facts"], "gazbeton_strength_n_mm2")["state"] == "missing"


def test_signed_or_approved_must_never_be_inferred_from_found_facts():
    item = SimpleNamespace(id="item", source_row=2, revision_id=None)
    facts = [{"key":"gazbeton_strength_n_mm2","label":"Dayanım",
              "value":2.5,"state":"found_for_review"}]
    result = _safe_result(
        item=item, document_sha="abc", document_status="found_for_review",
        candidate=None, position_status="unselected", flags=[], facts=facts,
        scope_conflict=None,
    )
    assert result["engineering_approved"] is False
    assert result["cost_allowed"] is False
    assert result["approval_allowed"] is False


def test_no_other_organization_access(client):
    from test_a326_project_evidence import project_with_metraj
    owner = register(client, "A347 owner", "a347owner@example.com")
    outsider = register(client, "A347 outsider", "a347outsider@example.com")
    pid, iid, ids = project_with_metraj(client, owner)
    url = f"/api/projects/{pid}/a347/imports/{iid}/items/{ids[0]}/completion"
    assert client.get(url, headers=outsider).status_code == 404


def test_scope_splits_material_labor_demolition_and_combined():
    from app.a347_spec_completion import work_scope
    assert work_scope("PVC zemin kaplaması malzeme temini") == "material_only"
    assert work_scope("PVC zemin kaplaması işçiliği (malzeme hariç)") == "labor_only"
    assert work_scope("Gazbeton duvar yapılması malzeme ve işçilik dahil") == "material_and_labor"
    assert work_scope("Mevcut seramik zemin kaplaması sökülmesi") == "demolition"
    assert work_scope("Bilinmeyen ürün") == "unspecified"
