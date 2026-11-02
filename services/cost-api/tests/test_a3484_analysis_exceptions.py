"""A3.48.4: formula-only official depth surcharges and safe source reindex."""
import json

import pymupdf

from app.a348_analysis_library_api import _extract
from test_a348_analysis_library_api import fake_analysis_pdf, sample_position
from test_a348_official_price_list import source_pdf


def formula_pdf() -> bytes:
    pdf = pymupdf.open()
    for n in range(10):
        page = pdf.new_page(width=595, height=842)
        if n == 5:
            page.insert_text((280, 72), "Analizin", fontsize=8)
            page.insert_text((45, 99), "15.110.1001", fontsize=8)
            page.insert_text((145, 99), "Derinlik zammi (iksasiz)", fontsize=8)
            page.insert_text((527, 99), "m³", fontsize=8)
            page.insert_text((150, 125), "Tanimi", fontsize=8)
            page.insert_text((145, 175), "Derinlik zammi F= M x ( H - 2 ) x K", fontsize=8)
            page.insert_text((145, 270), "M: 0,50.", fontsize=8)
            page.insert_text((125, 330), "Fiyati", fontsize=8)
        if n == 6:
            page.insert_text((280, 72), "Analizin", fontsize=8)
            page.insert_text((45, 99), "15.110.1002", fontsize=8)
            page.insert_text((145, 99), "Derinlik zammi (iksali)", fontsize=8)
            page.insert_text((527, 99), "m³", fontsize=8)
            page.insert_text((150, 125), "Tanimi", fontsize=8)
            page.insert_text((145, 175), "Derinlik zammi F= M x ( H - 2 ) x K", fontsize=8)
            page.insert_text((145, 270), "M: 1,00.", fontsize=8)
            page.insert_text((125, 330), "Fiyati", fontsize=8)
    result = pdf.tobytes()
    pdf.close()
    return result


def test_formula_only_poz_entries_keep_null_prices(monkeypatch):
    from app import a348_analysis_library_api as mod
    monkeypatch.setattr(mod, "read_positions", lambda raw: [])
    data = _extract(formula_pdf())
    assert data["audit"]["headers_detected"] == 2
    assert data["audit"]["unparsed_header_count"] == 0
    assert data["audit"]["parameterized_formula_count"] == 2
    assert data["audit"]["analysis_price_needs_review_count"] == 0
    records = {row["code"]: row for row in data["records"]}
    assert set(records) == {"15.110.1001", "15.110.1002"}
    assert records["15.110.1001"]["formula_parameters"]["M"] == "0,50"
    assert records["15.110.1002"]["formula_parameters"]["M"] == "1,00"
    for row in records.values():
        assert row["analysis_price"] is None
        assert row["inputs"] == []
        assert row["analysis_kind"] == "parameterized_formula"
        assert row["cost_allowed"] is False
        assert "F =" in row["formula"]


def test_formula_fallback_fails_closed_when_money_price_printed(monkeypatch):
    from app import a348_analysis_library_api as mod
    monkeypatch.setattr(mod, "read_positions", lambda raw: [])
    pdf = pymupdf.open(stream=formula_pdf(), filetype="pdf")
    pdf[5].insert_text((535, 330), "123,45", fontsize=8)
    raw = pdf.tobytes()
    pdf.close()
    data = mod._extract(raw)
    assert data["audit"]["parameterized_formula_count"] == 1
    assert data["audit"]["unparsed_header_count"] == 1
    assert [row["code"] for row in data["records"]] == ["15.110.1002"]


def test_reindex_old_source_without_modifying_original_pdf_or_index(client, auth, monkeypatch):
    from app import a348_analysis_library_api as mod
    monkeypatch.setattr(mod, "read_positions", lambda raw: [sample_position()])
    assert client.post("/api/a348/catalog/source", headers=auth,
                       files={"file": ("price.pdf", source_pdf())}).status_code == 201
    raw = fake_analysis_pdf()
    uploaded = client.post("/api/a348/catalog/analysis/source", headers=auth,
                           files={"file": ("analysis.pdf", raw)})
    assert uploaded.status_code == 201, uploaded.text

    from app.models import User
    from app.security import current_user
    from sqlalchemy import select
    from app.database import get_db
    # Read-only checks derive directory from stored organization scope, not project.
    first_user = next(iter(client.app.dependency_overrides[get_db]()))
    user = first_user.scalar(select(User))
    root = mod._root(user)
    folder = root / uploaded.json()["source_sha256"]
    pdf_file = folder / "source.pdf"
    prior_pdf = pdf_file.read_bytes()
    before_index = (folder / mod.INDEX_FILE).read_bytes()
    first = client.post("/api/a348/catalog/analysis/reindex", headers=auth)
    assert first.status_code == 200, first.text
    assert first.json()["position_count"] == 1
    assert pdf_file.read_bytes() == prior_pdf
    assert (folder / mod.INDEX_FILE).read_bytes() == before_index
    pointer = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert pointer["index_file"] == mod.INDEX_FILE
    assert client.post("/api/a348/catalog/analysis/reindex", headers=auth).status_code == 200
    assert client.get("/api/a348/catalog/linkage", headers=auth).json()["linked_count"] == 1
