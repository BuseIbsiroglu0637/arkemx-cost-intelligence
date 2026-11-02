"""A3.48.3 exact PDF poz-code linkage, independently versioned per tenant."""
from decimal import Decimal

from app.a318_pdf_engine import PdfPosition
from test_a348_official_price_list import source_pdf
from test_api import register


PRICE = "/api/a348/catalog/source"
ANALYSIS = "/api/a348/catalog/analysis/source"
DETAIL = "/api/a348/catalog/positions/15.225.1004/analysis"


def fake_analysis_pdf():
    """An actual PDF byte stream; parser output is stubbed for API isolation tests."""
    import pymupdf
    pdf = pymupdf.open()
    for i in range(10):
        p = pdf.new_page()
        if i == 5:
            p.insert_text((40, 40), "1.01.2026")
    raw = pdf.tobytes()
    pdf.close()
    return raw


def sample_position():
    return PdfPosition(
        id="15.225.1004", description="10 cm gazbeton duvar",
        unit="m²", price=Decimal("723.73"), price_verified=True, pdf_page=6,
        ingredients=({
            "code": "10.100.1062", "description": "İşçilik",
            "unit": "Sa", "quantity": "1",
            "unit_price": "578,98", "amount": "578,98",
        },),
        scope="PDF kaynak teknik kapsamı",
    )


def test_analysis_source_auth_and_not_uploaded(client, auth):
    assert client.get(ANALYSIS).status_code == 401
    assert client.post(ANALYSIS, files={"file": ("analysis.pdf", fake_analysis_pdf())}).status_code == 401
    assert client.get(ANALYSIS, headers=auth).json()["present"] is False
    assert client.get(DETAIL, headers=auth).status_code == 409


def test_upload_link_by_exact_code_and_display_inputs(client, auth, monkeypatch):
    from app import a348_analysis_library_api as mod
    monkeypatch.setattr(mod, "read_positions", lambda raw: [sample_position()])
    price_upload = client.post(PRICE, headers=auth, files={"file": ("price.pdf", source_pdf())})
    assert price_upload.status_code == 201, price_upload.text
    before = client.get(DETAIL, headers=auth).json()
    assert before["available"] is False and before["reason"] == "analysis_pdf_not_uploaded"

    analysis_binary = fake_analysis_pdf()
    uploaded = client.post(ANALYSIS, headers=auth, files={"file": ("cilt1.pdf", analysis_binary)})
    assert uploaded.status_code == 201, uploaded.text
    status = uploaded.json()
    assert status["present"] is True
    assert status["position_count"] == 1
    assert status["pdf_pages"] == 10
    assert status["read_only"] is True
    assert status["approval_allowed"] is False and status["cost_allowed"] is False

    detail = client.get(DETAIL, headers=auth)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert detail.headers["cache-control"] == "private, no-store"
    assert data["code"] == "15.225.1004"
    assert data["list_price"] == "723.73"
    assert data["price_list_pdf_page"] == 9
    assert data["analysis_source_sha256"] == status["source_sha256"]
    assert data["analysis"]["pdf_page"] == 6
    assert data["analysis"]["inputs"][0]["code"] == "10.100.1062"
    assert data["analysis"]["inputs"][0]["amount"] == "578,98"
    assert data["analysis"]["analysis_price_reconciled"] is True
    assert data["list_analysis_price_equal"] is True
    assert data["cost_allowed"] is False and data["approval_allowed"] is False

    # A Cilt 1 input code is not a price-list poz approval or a synthetic price.
    assert client.get("/api/a348/catalog/positions/15.225.1001/analysis",
                      headers=auth).status_code == 404
    assert client.get("/api/a348/catalog/positions/10.100.1062/analysis",
                      headers=auth).status_code == 422
    assert client.get("/api/projects", headers=auth).json() == []
    # Uploading again keeps the exact same source version, no overwrites.
    again = client.post(ANALYSIS, headers=auth, files={"file": ("again.pdf", analysis_binary)})
    assert again.status_code == 201 and again.json()["source_sha256"] == status["source_sha256"]


def test_missing_analysis_for_catalog_poz_is_not_fabricated(client, auth, monkeypatch):
    from app import a348_analysis_library_api as mod
    unmatched = PdfPosition(
        id="15.105.1001", description="Başka poz", unit="m²",
        price=Decimal("100"), price_verified=False, pdf_page=6,
        ingredients=({"code":"10.100.1062", "description":"Düz işçi",
                      "unit":"Sa", "quantity":"1",
                      "unit_price":"100,00", "amount":"100,00"},),
        scope="",)
    monkeypatch.setattr(mod, "read_positions", lambda raw: [unmatched])
    assert client.post(PRICE, headers=auth,
                       files={"file": ("price.pdf", source_pdf())}).status_code == 201
    assert client.post(ANALYSIS, headers=auth,
                       files={"file": ("analysis.pdf", fake_analysis_pdf())}).status_code == 201
    result = client.get(DETAIL, headers=auth).json()
    assert result["available"] is False
    assert result["reason"] == "analysis_not_in_cilt_1_or_not_parsed"
    assert result["analysis"] is None


def test_analysis_is_private_to_organization_and_wrong_pdf_rejected(client, monkeypatch):
    from app import a348_analysis_library_api as mod
    first = register(client, "Poz Analysis First", "pozanalysis_first@example.com")
    other = register(client, "Poz Analysis Other", "pozanalysis_other@example.com")
    monkeypatch.setattr(mod, "read_positions", lambda raw: [sample_position()])
    assert client.post(PRICE, headers=first,
                       files={"file": ("price.pdf", source_pdf())}).status_code == 201
    assert client.post(PRICE, headers=other,
                       files={"file": ("price.pdf", source_pdf())}).status_code == 201
    assert client.post(ANALYSIS, headers=first,
                       files={"file": ("analysis.pdf", fake_analysis_pdf())}).status_code == 201
    assert client.get(ANALYSIS, headers=other).json()["present"] is False
    assert client.get(DETAIL, headers=other).json()["reason"] == "analysis_pdf_not_uploaded"
    bad = client.post(ANALYSIS, headers=other, files={"file": ("notpdf.pdf", b"NOT PDF")})
    assert bad.status_code == 422
    assert client.get(ANALYSIS, headers=other).json()["present"] is False
