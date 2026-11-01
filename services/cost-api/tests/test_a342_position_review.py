"""A3.42 manual poz is a durable lookup request, never automatic approval."""
from decimal import Decimal
from dataclasses import replace

from app import a318_pdf_api
from app.a318_pdf_engine import PdfPosition
from app.technical import compare
from test_a318_pdf_api import setup, positions


def test_unknown_material_label_does_not_hide_explicit_technical_conflicts():
    unknown = compare(
        "PVC işçilik", "m²",
        "PVC kapı pencere doğraması sökülmesi", "m²",
    )
    assert "MATERIAL_UNVERIFIED" not in unknown["review_flags"]
    assert unknown["status"] == "review"  # Sökme işi metrajda tanımlı değil.
    assert "METHOD_UNVERIFIED" in unknown["review_flags"]

    contradictory = compare(
        "Epoksi kaplama", "m²", "Poliüretan kaplama", "m²",
    )
    assert contradictory["status"] == "blocked"
    assert "MATERIAL_MISMATCH" in contradictory["blockers"]


def test_manual_poz_survives_missing_pdf_and_reconciles_with_new_pdf(
    client, auth, monkeypatch,
):
    pid, iid = setup(client, auth, "Manual deferred poz")
    prefix = f"/api/projects/{pid}/a318"
    url = f"{prefix}/imports/{iid}/suggestions"
    # No PDF required to record the user's own poz number.
    row = client.get(f"/api/projects/{pid}/a3/imports/{iid}/items", headers=auth)
    assert row.status_code == 200, row.text
    first = row.json()["rows"][0]
    item_id = first["work_item_id"]
    save_url = f"{prefix}/imports/{iid}/items/{item_id}/manual-position"
    request = {
        "position_code": "15.999.1999",
        "expected_revision_id": first["revision_id"],
    }
    stored = client.post(save_url, headers=auth, json=request)
    assert stored.status_code == 200, stored.text
    manual = stored.json()["manual_position"]
    assert manual["position_code"] == "15.999.1999"
    assert manual["pdf_found"] is False
    assert manual["can_select"] is False
    assert manual["cost_allowed"] is False

    # First official PDF edition cannot match the entered code.
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    upload = client.post(
        f"{prefix}/source", headers=auth,
        data={"rights_confirmed": "true"},
        files={"file": ("first.pdf", b"%PDF-" + b"A" * 1500)},
    )
    assert upload.status_code == 201, upload.text
    result = client.get(url, headers=auth)
    assert result.status_code == 200, result.text
    before = result.json()["rows"][0]["manual_position"]
    assert before["position_code"] == "15.999.1999"
    assert before["pdf_found"] is False
    assert before["can_select"] is False
    assert before["cost_allowed"] is False

    # A newly uploaded edition includes the exact manually entered poz.
    source = PdfPosition(
        id="15.999.1999",
        description="Seramik 60x60 zemin kaplaması",
        unit="m²", price=Decimal("221.88"), price_verified=True,
        pdf_page=42, scope="Sentetik test poz açıklaması",
        ingredients=({"code": "10.999.1001", "description": "Test", "unit": "m²",
                      "quantity": "1", "unit_price": "177,50", "amount": "177,50"},),
    )
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: (source,))
    updated = client.post(
        f"{prefix}/source", headers=auth,
        data={"rights_confirmed": "true"},
        files={"file": ("new.pdf", b"%PDF-" + b"B" * 1500)},
    )
    assert updated.status_code == 201, updated.text
    after = client.get(url, headers=auth)
    assert after.status_code == 200, after.text
    restored = after.json()["rows"][0]["manual_position"]
    assert restored["pdf_found"] is True
    assert restored["can_select"] is True
    assert restored["pdf_match"]["code"] == "15.999.1999"
    assert restored["cost_allowed"] is False
    assert restored["engineering_approved"] is False

    # Only the explicit PDF-backed candidate-save workflow can promote
    # a manual lookup to a selected *candidate*, not a priced or approved item.
    linked = client.post(
        f"{prefix}/imports/{iid}/items/{item_id}/candidate", headers=auth,
        json={
            "position_code": "15.999.1999",
            "expected_revision_id": first["revision_id"],
            "expected_pdf_sha256": updated.json()["sha256"],
        },
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["engineering_approved"] is False
    assert linked.json()["cost_allowed"] is False


def test_manual_poz_is_tenant_scoped(client, monkeypatch):
    from test_api import register
    first = register(client, "A342 first", "a342first@example.com")
    other = register(client, "A342 second", "a342other@example.com")
    pid, iid = setup(client, first, "Tenant manual poz")
    response = client.get(
        f"/api/projects/{pid}/a3/imports/{iid}/items", headers=first,
    )
    item = response.json()["rows"][0]
    url = f"/api/projects/{pid}/a318/imports/{iid}/items/{item['work_item_id']}/manual-position"
    assert client.post(url, headers=other, json={
        "position_code": "15.999.1999", "expected_revision_id": item["revision_id"],
    }).status_code == 404
