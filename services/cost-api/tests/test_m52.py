"""M5.2 revised Excel: safe preview, explicit apply, immutability and rights guards."""
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy import select
from app.database import get_db
from app.models import ImportBatch, MetrajRevisionEvent
from test_m5 import setup, approve, price_payload
from test_m41 import auth


def xlsx(items):
    book = Workbook()
    ws = book.active
    ws.title = "Mimari Metraj"
    ws.append(["İmalat Açıklaması", "Miktar", "Birim"])
    for item in items:
        ws.append(item)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


ORIGINAL = "Hazır beton döküm C25/30 nakliye dahildir"


def base(client, monkeypatch):
    head, pid, _, run, cand = setup(client, monkeypatch)
    approve(client, head, pid, run, cand)
    body = price_payload(run, cand["candidate_id"], key="m52-original-m5-price", price="1250")
    created = client.post(f"/api/projects/{pid}/m5/estimates", headers=head, json=body)
    assert created.status_code == 201, created.text
    return head, pid, created.json()["id"]


def preview(client, head, pid, content, estimate_id=None):
    return client.post(f"/api/projects/{pid}/m52/preview", headers=head,
        data={"estimate_id": estimate_id} if estimate_id else {},
        files={"file": ("revision.xlsx", content)})


def apply(client, head, pid, content, reviewed, reason="Actual architect revision accepted for synthetic pilot"):
    return client.post(f"/api/projects/{pid}/m52/apply", headers=head,
        data={
            "expected_baseline_id": reviewed["baseline_import_id"],
            "expected_revision_sha256": reviewed["revision_sha256"],
            "estimate_id": reviewed.get("baseline_estimate_id") or "",
            "reason": reason,
        },
        files={"file": ("revision.xlsx", content)})


def test_m52_preview_and_explicit_import_preserves_original_and_m5(client, monkeypatch):
    head, pid, estimate_id = base(client, monkeypatch)
    content = xlsx([(ORIGINAL, 13, "m3")])
    response = preview(client, head, pid, content, estimate_id)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["row_count_old"] == 1 and data["row_count_new"] == 1
    assert data["counts"] == {"quantity_changed": 1}
    assert data["changed_rows"] == 1
    assert data["known_quantity_effect"] == "625.00"
    assert not data["unknown_cost_effect"]
    assert data["fully_attributable_quantity_effect"] == "625.00"
    assert data["requires_fresh_m43"] and not data["approvals_transferred"]
    initial = client.get(f"/api/projects/{pid}/imports", headers=head).json()
    assert len(initial) == 1  # preview did not persist anything

    fail = client.post(f"/api/projects/{pid}/m52/apply", headers=head,
        data={"expected_baseline_id": data["baseline_import_id"],
              "expected_revision_sha256": "0" * 64,
              "reason": "Synthetic revised worksheet accepted",
              "estimate_id": estimate_id},
        files={"file": ("revision.xlsx", content)})
    assert fail.status_code == 409
    assert len(client.get(f"/api/projects/{pid}/imports", headers=head).json()) == 1

    applied = apply(client, head, pid, content, data)
    assert applied.status_code == 201, applied.text
    result = applied.json()
    assert result["changed_rows"] == 1
    assert result["approvals_transferred"] is False
    imports = client.get(f"/api/projects/{pid}/imports", headers=head).json()
    assert len(imports) == 2
    assert imports[0]["id"] == result["import_id"]
    assert imports[1]["sha256"] == data["baseline_sha256"]
    history = client.get(f"/api/projects/{pid}/m52/history", headers=head)
    assert history.status_code == 200
    assert history.json()[0]["new_import_id"] == result["import_id"]
    assert history.json()[0]["counts"] == {"quantity_changed": 1}

    # Historical cost evidence remains readable and unchanged.
    old = client.get(f"/api/projects/{pid}/m5/estimates/{estimate_id}", headers=head)
    assert old.status_code == 200
    assert old.json()["total"] == "15625.00"
    assert old.json()["lines"][0]["quantity"] == "12.5000"
    # Old approval is stale for the newly imported Excel.
    assert client.get(f"/api/projects/{pid}/m5/eligible", headers=head).status_code == 409
    assert apply(client, head, pid, content, data).status_code == 409


def test_m52_scope_change_added_removed_and_uncertainty(client, monkeypatch):
    head, pid, estimate_id = base(client, monkeypatch)
    content = xlsx([("Hazır beton döküm C30/37 nakliye dahildir", 13, "m3"),
                    ("Yeni şap uygulaması", 4, "m2")])
    d = preview(client, head, pid, content, estimate_id)
    assert d.status_code == 200, d.text
    result = d.json()
    assert result["counts"]["identity_or_scope_changed"] == 1
    assert result["counts"]["added"] == 1
    assert result["unknown_cost_effect"]
    assert result["fully_attributable_quantity_effect"] is None
    assert result["items"][0]["indicative_delta"] is None
    assert result["items"][0]["requires_engineer_review"] is True
    assert result["changed_rows"] == 2


def test_m52_invalid_upload_and_tenant_guards(client, monkeypatch):
    head, pid, estimate_id = base(client, monkeypatch)
    outsider = auth(client, "Other M52 Office", "outsider-m52@example.com")
    data = xlsx([(ORIGINAL, 14, "m3")])
    assert preview(client, outsider, pid, data, estimate_id).status_code == 404
    assert preview(client, head, pid, b"not-an-excel", estimate_id).status_code == 422
    reviewed = preview(client, head, pid, data, estimate_id).json()
    assert client.post(f"/api/projects/{pid}/m52/apply", headers=outsider, data={
        "expected_baseline_id": reviewed["baseline_import_id"],
        "expected_revision_sha256": reviewed["revision_sha256"],
        "reason": "This user should not modify other office data",
    }, files={"file": ("revision.xlsx", data)}).status_code == 404
    assert client.get(f"/api/projects/{pid}/m52/history", headers=outsider).status_code == 404


def test_m52_duplicate_descriptions_never_auto_paired(client, monkeypatch):
    head, pid, _ = base(client, monkeypatch)
    duplicated = xlsx([(ORIGINAL, 13, "m3"), (ORIGINAL, 13, "m3")])
    response = preview(client, head, pid, duplicated)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["unknown_cost_effect"]
    assert result["items"][0]["status"] == "duplicate_identity_review"
    assert result["items"][1]["status"] == "added"


def test_m52_revised_excel_formula_and_unit_require_review(client, monkeypatch):
    head, pid, _ = base(client, monkeypatch)
    content = xlsx([(ORIGINAL, "=SUM(3,9)", "m3")])
    response = preview(client, head, pid, content)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["review_count_new"] == 1
    assert result["items"][0]["status"] == "needs_data_review"
    assert "FORMULA_NOT_EVALUATED" in result["items"][0]["issues"]
    assert result["unknown_cost_effect"]

def test_m52_revision_audit_reason_tampering_fails_closed(client, monkeypatch):
    head, pid, estimate_id = base(client, monkeypatch)
    content = xlsx([(ORIGINAL, 13, "m3")])
    reviewed = preview(client, head, pid, content, estimate_id).json()
    result = apply(client, head, pid, content, reviewed)
    assert result.status_code == 201, result.text
    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    event = db.scalar(select(MetrajRevisionEvent).where(
        MetrajRevisionEvent.id == result.json()["id"]))
    event.reason = "Unauthorized rewrite of the original review rationale"
    db.commit()
    gen.close()
    assert client.get(f"/api/projects/{pid}/m52/history",
                      headers=head).status_code == 409
