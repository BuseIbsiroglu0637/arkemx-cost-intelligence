"""Source-attributed arithmetic and persisted workflow; no external PDF fixture."""
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.database import get_db
from app.models import User, WorkItemRevision, MetrajImportExclusion
from app.pilot_cost_store import PilotCostSnapshot


def upload(client, auth, pid, rows):
    book = Workbook()
    sheet = book.active
    sheet.append(["İmalat", "Miktar", "Birim"])
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    result = client.post(f"/api/projects/{pid}/imports", headers=auth,
                         files={"file": ("pilot.xlsx", stream.getvalue())})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def setup(client, auth, rows=None):
    pid = client.post("/api/projects", headers=auth, json={"name": "Kaynaklı pilot"}).json()["id"]
    upload(client, auth, pid, rows or [("C25/30 beton", 12.5, "m3"), ("İşçilik", 3, "adet")])
    base = f"/api/projects/{pid}/pilot-costs"
    source = client.get(base + "/source", headers=auth)
    assert source.status_code == 200, source.text
    return pid, base, source.json()


def prices(source, values=("1.250,00", "0,3350")):
    return {"import_id": source["import_id"], "prices": [
        {"work_item_id": row["work_item_id"], "unit": row["unit"], "unit_price": value,
         "source": "Tedarikçi ABC-42, sayfa 3", "source_date": "2026-01-01"}
        for row, value in zip(source["rows"], values)]}


def preview(client, auth, base, body):
    response = client.post(base + "/preview", headers=auth, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def save_body(body, report):
    return {**body, "title": "Kontrollü maliyet", "expected_preview_sha256": report["preview_sha256"],
            "request_key": str(uuid4()), "acknowledgement": "I_REVIEWED_QUANTITIES_UNITS_AND_PRICE_SOURCES"}


def test_excel_to_saved_report_csv_history_and_independent_arithmetic(client, auth):
    _, base, source = setup(client, auth)
    body = prices(source)
    report = preview(client, auth, base, body)
    # Independently hand-calculated: 12.5 * 1250 = 15625; 3 * .335 = 1.005 -> 1.01.
    assert report["total"] == "15626.01"
    assert report["coverage"] == "complete"
    assert report["excluded_count"] == 0
    assert report["engineering_approved"] is False
    assert report["official_prices_verified"] is False
    body = save_body(body, report)
    result = client.post(base + "/snapshots", headers=auth, json=body)
    assert result.status_code == 201, result.text
    saved = result.json()
    retry = client.post(base + "/snapshots", headers=auth, json=body)
    assert retry.status_code == 200 and retry.json()["id"] == saved["id"]
    assert client.post(base + "/snapshots", headers=auth, json={**body, "title": "Changed"}).status_code == 409
    assert client.get(base + "/snapshots", headers=auth).json()[0]["total"] == "15626.01"
    assert client.get(base + "/snapshots/" + saved["id"], headers=auth).json()["rows"] == saved["rows"]
    csv = client.get(base + "/snapshots/" + saved["id"] + "/csv", headers=auth)
    assert csv.status_code == 200 and "15626.01" in csv.text and "ABC-42" in csv.text
    assert "private, no-store" == csv.headers["cache-control"]


def test_missing_price_and_invalid_metraj_are_never_zero_priced_complete_costs(client, auth):
    _, base, source = setup(client, auth, [("Geçerli imalat", 2, "m2"), ("Belirsiz", "1.234", "m2")])
    report = preview(client, auth, base, prices(source, ("10",)))
    assert report["total"] == "20.00" and report["coverage"] == "partial"
    assert report["priced_count"] == report["excluded_count"] == 1
    assert report["rows"][1]["amount"] is None
    empty = {"import_id": source["import_id"], "prices": []}
    report = preview(client, auth, base, empty)
    assert report["priced_count"] == 0 and report["coverage"] == "partial"
    assert client.post(base + "/snapshots", headers=auth, json=save_body(empty, report)).status_code == 422


@pytest.mark.parametrize("value", ["1.234", "0", "-1", "NaN", "1e5", "1,250.00"])
def test_price_input_never_guesses_ambiguous_negative_or_non_decimal_values(client, auth, value):
    _, base, source = setup(client, auth)
    body = prices(source, (value,))
    assert client.post(base + "/preview", headers=auth, json=body).status_code == 422


def test_unit_source_date_duplicates_and_foreign_rows_are_rejected(client, auth):
    _, base, source = setup(client, auth)
    body = prices(source, ("10",))
    line = body["prices"][0]
    for override in ({"unit": "kg"}, {"source": "          "}, {"source_date": "bad"}, {"work_item_id": str(uuid4())}):
        response = client.post(base + "/preview", headers=auth,
                              json={**body, "prices": [{**line, **override}]})
        assert response.status_code == 422, response.text
    assert client.post(base + "/preview", headers=auth,
                       json={**body, "prices": [line, line]}).status_code == 422


def test_changed_excel_and_revised_quantity_require_new_preview_but_keep_history(client, auth):
    pid, base, source = setup(client, auth)
    body = prices(source)
    report = preview(client, auth, base, body)
    saved = client.post(base + "/snapshots", headers=auth, json=save_body(body, report)).json()
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    owner = db.scalar(select(User))
    db.add(WorkItemRevision(work_item_id=source["rows"][0]["work_item_id"], revision=1,
        description="C25/30 beton", quantity=13, unit="m³", corrected_by_id=owner.id, reason="Metraj düzeltmesi"))
    db.commit()
    generator.close()
    assert client.post(base + "/snapshots", headers=auth, json=save_body(body, report)).status_code == 409
    upload(client, auth, pid, [("Yeni metraj", 5, "m2")])
    assert client.post(base + "/preview", headers=auth, json=body).status_code == 409
    assert client.get(base + "/snapshots/" + saved["id"], headers=auth).json()["total"] == "15626.01"


def test_other_tenant_cannot_read_prices_or_write_reports(client, auth):
    _, base, source = setup(client, auth)
    body = prices(source)
    saved = client.post(base + "/snapshots", headers=auth,
                        json=save_body(body, preview(client, auth, base, body))).json()
    token = client.post("/api/auth/register", json={"organization_name": "Other office",
        "email": "outsider@example.com", "password": "other-secure-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    for suffix in ("/source", "/snapshots", "/snapshots/" + saved["id"], "/snapshots/" + saved["id"] + "/csv"):
        assert client.get(base + suffix, headers=other).status_code == 404
    assert client.post(base + "/preview", headers=other, json=body).status_code == 404
    assert client.post(base + "/preview", json=body).status_code == 401


def test_saved_report_tampering_is_blocked_and_csv_escapes_formulas(client, auth):
    _, base, source = setup(client, auth)
    body = prices(source)
    body["prices"][0]["source"] = "=SUM(A1:A10) teklif notu"
    report = preview(client, auth, base, body)
    saved = client.post(base + "/snapshots", headers=auth, json=save_body(body, report)).json()
    url = base + "/snapshots/" + saved["id"]
    assert "'=SUM" in client.get(url + "/csv", headers=auth).text
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    db.get(PilotCostSnapshot, saved["id"]).payload_json = "{}"
    db.commit()
    generator.close()
    assert client.get(url, headers=auth).status_code == 409
    assert client.get(url + "/csv", headers=auth).status_code == 409


@pytest.mark.parametrize("count", [100, 500])
def test_many_distinct_rows_import_price_save_and_reload(client, auth, count):
    _, base, source = setup(client, auth, [(f"İmalat {i}", 2, "m2") for i in range(count)])
    body = prices(source, ["10,1250"] * count)
    report = preview(client, auth, base, body)
    assert report["total"] == ("2025.00" if count == 100 else "10125.00")
    assert report["priced_count"] == count and report["coverage"] == "complete"
    saved = client.post(base + "/snapshots", headers=auth, json=save_body(body, report))
    assert saved.status_code == 201, saved.text
    assert len(client.get(base + "/snapshots/" + saved.json()["id"], headers=auth).json()["rows"]) == count


def test_501_rows_are_rejected_as_a_whole_instead_of_silently_truncated(client, auth):
    pid = client.post("/api/projects", headers=auth, json={"name": "Limit kontrolü"}).json()["id"]
    upload(client, auth, pid, [(f"İmalat {i}", 2, "m2") for i in range(501)])
    assert client.get(f"/api/projects/{pid}/pilot-costs/source", headers=auth).status_code == 422


def test_round_each_line_before_adding_instead_of_rounding_the_grand_total(client, auth):
    _, base, source = setup(client, auth, [("İmalat A", 1, "m2"), ("İmalat B", 1, "m2")])
    report = preview(client, auth, base, prices(source, ("0,0050", "0,0050")))
    assert [row["amount"] for row in report["rows"]] == ["0.01", "0.01"]
    assert report["total"] == "0.02"


def test_excluded_source_blocks_new_costs_but_preserves_saved_report(client, auth):
    pid, base, source = setup(client, auth)
    body = prices(source)
    saved = client.post(base + "/snapshots", headers=auth,
        json=save_body(body, preview(client, auth, base, body))).json()
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    owner = db.scalar(select(User))
    db.add(MetrajImportExclusion(import_id=source["import_id"], project_id=pid,
        organization_id=owner.organization_id, original_sha256=source["source_sha256"],
        excluded_by_id=owner.id, reason="Yanlış kaynak dosyası, yeni analiz dışında"))
    db.commit()
    generator.close()
    assert client.get(base + "/source", headers=auth).status_code == 409
    assert client.post(base + "/preview", headers=auth, json=body).status_code == 409
    assert client.get(base + "/snapshots/" + saved["id"], headers=auth).status_code == 200
