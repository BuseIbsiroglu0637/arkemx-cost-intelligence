"""A3.18 local PDF: authorization, tenant isolation, source evidence, no automatic pricing."""
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from app import a318_pdf_api
from app.a318_pdf_engine import PdfPosition, number
from test_api import xlsx_bytes


def positions():
    return (
        PdfPosition(
            id="15.999.1001", description="10 cm gazbeton duvar uygulaması",
            unit="m²", price=Decimal("100.00"), price_verified=True,
            pdf_page=5, scope="Sentetik test poz açıklaması",
            ingredients=({"code": "10.999.1001", "description": "Test malzemesi",
                          "unit": "m²", "quantity": "1", "unit_price": "100,00", "amount": "100,00"},),
        ),
        PdfPosition(
            id="15.999.1002", description="Seramik duvar kaplaması",
            unit="m²", price=Decimal("120.00"), price_verified=False,
            pdf_page=7, scope="Sentetik test poz kapsamı", ingredients=(),
        ),
    )


def setup(client, auth, title="Direct PDF pilot"):
    p = client.post("/api/projects", headers=auth, json={"name": title})
    assert p.status_code == 201, p.text
    pid = p.json()["id"]
    i = client.post(f"/api/projects/{pid}/imports", headers=auth,
                    files={"file": ("metraj.xlsx", xlsx_bytes())})
    assert i.status_code == 201, i.text
    return pid, i.json()["id"]


def upload(client, pid, auth, confirmed="true"):
    return client.post(
        f"/api/projects/{pid}/a318/source",
        headers=auth,
        data={"rights_confirmed": confirmed},
        files={"file": ("analysis.pdf", b"%PDF-" + b"A" * 1500, "application/pdf")},
    )


def test_requires_explicit_rights_confirmation(client, auth, monkeypatch):
    pid, _ = setup(client, auth)
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    denied = upload(client, pid, auth, "false")
    assert denied.status_code == 403
    assert client.get(f"/api/projects/{pid}/a318/source", headers=auth).json()["present"] is False


def test_upload_and_direct_suggestion_are_read_only(client, auth, monkeypatch):
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    pid, iid = setup(client, auth)
    uploaded = upload(client, pid, auth)
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["position_count"] == 2
    assert uploaded.json()["verified_price_count"] == 1
    status = client.get(f"/api/projects/{pid}/a318/source", headers=auth)
    assert status.json()["sha256"] == uploaded.json()["sha256"]
    suggested = client.get(f"/api/projects/{pid}/a318/imports/{iid}/suggestions", headers=auth)
    assert suggested.status_code == 200, suggested.text
    data = suggested.json()
    assert data["read_only"] is True
    assert data["cost_allowed"] is False
    assert data["approval_allowed"] is False
    assert data["catalog"]["synthetic"] is False
    assert data["catalog"]["version_id"] == uploaded.json()["sha256"]
    assert data["rows"] and any(row["suggestions"] for row in data["rows"])
    assert all(candidate["source_price"] is None or candidate["source_price_verified"]
               for row in data["rows"] for candidate in row["suggestions"])
    assert suggested.headers["cache-control"] == "private, no-store"


def test_other_organization_cannot_see_pdf_source(client, monkeypatch):
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    def register(name, email):
        r = client.post("/api/auth/register", json={
            "organization_name": name, "email": email,
            "password": "secure-pilot-password",
        })
        assert r.status_code == 201, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    first = register("Tenant one", "one318@example.com")
    second = register("Tenant two", "two318@example.com")
    pid, iid = setup(client, first, "First project")
    other_pid, _ = setup(client, second, "Second project")
    assert upload(client, pid, first).status_code == 201
    assert client.get(f"/api/projects/{other_pid}/a318/source", headers=second).json()["present"] is False
    url = f"/api/projects/{pid}/a318/imports/{iid}/suggestions"
    assert client.get(url, headers=second).status_code == 404


def test_failed_pdf_replacement_preserves_last_source(client, auth, monkeypatch):
    pid, _ = setup(client, auth)
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    old = upload(client, pid, auth)
    assert old.status_code == 201
    sha = old.json()["sha256"]
    def bad_parser(*args):
        raise ValueError("Unsupported PDF")
    monkeypatch.setattr(a318_pdf_api, "_parse", bad_parser)
    assert upload(client, pid, auth).status_code == 422
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: positions())
    status = client.get(f"/api/projects/{pid}/a318/source", headers=auth)
    assert status.json()["sha256"] == sha


def test_tr_decimal_parser_is_explicit():
    assert number("1.706,83") == Decimal("1706.83")
    assert number("-0,05") == Decimal("-0.05")
    assert number("unknown") is None


def test_combined_plaster_warning_keeps_two_original_rows(client, auth, monkeypatch):
    monkeypatch.setattr(a318_pdf_api, "_parse", lambda *args: (
        PdfPosition(
            id="15.999.2751", description="20 mm kaba sıva ve 8 mm ince sıva yapılması",
            unit="m²", price=Decimal("700"), price_verified=True,
            pdf_page=40, ingredients=(), scope="İki katmanlı sıva analizi",
        ),
    ))
    pid = client.post("/api/projects", headers=auth,
                      json={"name": "Plaster pair"}).json()["id"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["İmalat", "Miktar", "Birim"])
    sheet.append(["20 mm çimento esaslı kaba sıva", 168.5, "m²"])
    sheet.append(["8 mm ince sıva uygulaması", 168.5, "m²"])
    buffer = BytesIO()
    workbook.save(buffer)
    imp = client.post(f"/api/projects/{pid}/imports", headers=auth,
                      files={"file": ("plaster.xlsx", buffer.getvalue())})
    assert imp.status_code == 201, imp.text
    assert upload(client, pid, auth).status_code == 201
    response = client.get(
        f"/api/projects/{pid}/a318/imports/{imp.json()['id']}/suggestions",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["cost_allowed"] is False
    assert data["approval_allowed"] is False
    rows = data["rows"]
    assert len(rows) == 2
    assert rows[0]["related_excel_rows"] == [3]
    assert rows[1]["related_excel_rows"] == [2]
    assert all("birleşik" in row["review_summary"] for row in rows)
    assert any("POSSIBLE_COMBINED_PLASTER_SCOPE" in row["suggestions"][0]["review_flags"]
               for row in rows if row["suggestions"])
