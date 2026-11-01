"""A3.41: incomplete matches remain deferred without blocking priced rows."""
from io import BytesIO

from openpyxl import Workbook

from test_m41 import auth, grant, project_and_catalog


def test_one_approved_row_can_be_priced_while_another_has_no_match(client, monkeypatch):
    headers = auth(client, "A341 Partial Pilot", "a341partial@example.com")
    project_id, catalog = project_and_catalog(client, headers)

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["İmalat Açıklaması", "Miktar", "Birim"])
    sheet.append(["Hazır beton döküm C25/30 nakliye dahildir", "12,5", "m3"])
    sheet.append(["Belirsiz teknik ekipman montajı - açıklama eksik", "5", "adet"])
    data = BytesIO()
    workbook.save(data)

    uploaded = client.post(
        f"/api/projects/{project_id}/imports", headers=headers,
        files={"file": ("a341-partial.xlsx", data.getvalue())},
    )
    assert uploaded.status_code == 201, uploaded.text

    grant(client, monkeypatch, catalog["id"])
    matching = client.post(
        f"/api/m3/projects/{project_id}/run", headers=headers,
        json={"version_id": catalog["version_id"]},
    )
    assert matching.status_code == 201, matching.text
    run = client.post(f"/api/projects/{project_id}/m41/run", headers=headers)
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]

    url = f"/api/projects/{project_id}/m5/eligible"
    initial = client.get(url, headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["eligible_count"] == 0
    assert initial.json()["pending_count"] == 2

    compatible = client.get(
        f"/api/projects/{project_id}/m42/queue",
        headers=headers, params={"status": "compatible"},
    )
    assert compatible.status_code == 200, compatible.text
    good = next(
        row for row in compatible.json()["rows"]
        if row["code"] == "DEMO-C25" and row["source_row"] == 2
    )

    approved = client.post(
        f"/api/projects/{project_id}/m2/decisions", headers=headers,
        json={
            "run_id": run_id, "candidate_id": good["candidate_id"],
            "action": "approve",
            "reason": "Independent technical and source scope compatibility check",
        },
    )
    assert approved.status_code == 201, approved.text

    result = client.get(url, headers=headers)
    assert result.status_code == 200, result.text
    snapshot = result.json()
    assert snapshot["row_count"] == 2
    assert snapshot["eligible_count"] == 1
    assert snapshot["pending_count"] == 1
    assert snapshot["is_partial"] is True
    assert snapshot["pending_items"][0]["source_row"] == 3
    assert snapshot["pending_items"][0]["amount"] is None
    assert snapshot["items"][0]["source_row"] == 2

    # Pending row has no price and is not part of the persisted total.
    cost = client.post(
        f"/api/projects/{project_id}/m5/estimates", headers=headers,
        json={
            "run_id": run_id, "request_key": "a341-partial-cost-0001",
            "title": "Yalnızca onaylı pozların kısmi maliyeti",
            "lines": [{
                "candidate_id": good["candidate_id"],
                "unit_price": "123.4500",
                "price_source": "Synthetic manually entered regression test price",
            }],
        },
    )
    assert cost.status_code == 201, cost.text
    assert cost.json()["total"] == "1543.13"
    assert cost.json()["line_count"] == 1
