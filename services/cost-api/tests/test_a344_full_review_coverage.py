"""A3.44 — all imported lines receive an advisory, PDF-bound review status."""
from io import BytesIO
from openpyxl import Workbook

from app import a318_pdf_api
from test_a318_pdf_api import positions, upload


def test_full_import_coverage_is_not_confused_with_current_page_or_cost(client, auth, monkeypatch):
    p = client.post("/api/projects", headers=auth, json={"name": "A344 full review"})
    assert p.status_code == 201, p.text
    project_id = p.json()["id"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["İmalat", "Metraj", "Ölçü Birimi"])
    for row in range(25):
        sheet.append([
            "10 cm gazbeton duvar uygulaması" if row % 2 == 0
            else "Belirsiz özel PVC ürün malzemesi",
            "12,50", "m2",
        ])
    content = BytesIO()
    workbook.save(content)
    imp = client.post(
        f"/api/projects/{project_id}/imports", headers=auth,
        files={"file": ("25-lines.xlsx", content.getvalue())},
    )
    assert imp.status_code == 201, imp.text
    import_id = imp.json()["id"]
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    source = upload(client, project_id, auth)
    assert source.status_code == 201, source.text

    base = f"/api/projects/{project_id}/a318/imports/{import_id}"
    page = client.get(f"{base}/suggestions", headers=auth)
    assert page.status_code == 200, page.text
    assert len(page.json()["rows"]) == 20

    result = client.get(f"{base}/review-coverage", headers=auth)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["schema"] == "arkemx.a344.review_coverage.v1"
    assert data["read_only"] is True
    assert data["cost_allowed"] is False
    assert data["approval_allowed"] is False
    assert data["source_sha256"] == source.json()["sha256"]
    assert data["total_rows"] == data["scanned_rows"] == 25
    assert data["complete"] is True
    assert len(data["rows"]) == 25
    assert len({r["work_item_id"] for r in data["rows"]}) == 25
    assert all(r["cost_allowed"] is False and r["engineering_approved"] is False
               for r in data["rows"])
    counts = data["counts"]
    assert (counts["no_match"] + counts["needs_info"] +
            counts["needs_review"] + counts["rule_prechecked"]) == 25
    assert result.headers["cache-control"] == "private, no-store"


def test_full_import_coverage_is_tenant_restricted(client, monkeypatch):
    from test_api import register, xlsx_bytes
    first = register(client, "A344 company one", "a344one@example.com")
    other = register(client, "A344 company two", "a344two@example.com")
    p = client.post("/api/projects", headers=first, json={"name": "Private"})
    assert p.status_code == 201
    pid = p.json()["id"]
    imp = client.post(
        f"/api/projects/{pid}/imports", headers=first,
        files={"file": ("private.xlsx", xlsx_bytes())},
    )
    assert imp.status_code == 201
    path = f"/api/projects/{pid}/a318/imports/{imp.json()['id']}/review-coverage"
    assert client.get(path, headers=other).status_code == 404
