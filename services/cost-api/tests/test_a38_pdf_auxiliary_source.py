"""Verify actual mortar auxiliary PDFs and their link to the parent analysis."""

import os
from decimal import Decimal

import pytest

from app.technical_analysis.pdf_analysis_source import read_analysis
from app.technical_analysis.pdf_auxiliary_source import (
    parse_auxiliary_text,
    read_auxiliary_analysis,
)

CODES = ("19.100.2504", "19.100.2506", "19.100.2508")
EXPECTED = {
    "19.100.2504": (696, "10.130.1005", "0.25", "0.215", "1706.83"),
    "19.100.2506": (697, "10.130.1007", "0.3", "0.23", "1926.15"),
    "19.100.2508": (698, "10.130.1007", "0.35", "0.245", "2054.48"),
}


@pytest.fixture(scope="module", params=CODES)
def analysis(request):
    path = os.environ.get("ARKEMX_AUXILIARY_PDF")
    assert path, "ARKEMX_AUXILIARY_PDF must be set"
    return read_auxiliary_analysis(path, request.param)


@pytest.mark.external_pdf
def test_identity_and_resource_types(analysis):
    page, sand, cement, water, _ = EXPECTED[analysis["position_code"]]
    rows = analysis["resources"]
    assert analysis["unit"] == "m³"
    assert analysis["source"]["pdf_page"] == page
    assert analysis["source"]["sha256"] == (
        "ca7453f9e8d583e28bb16130b19487edc8308831017d8d7e4daa0367c8038431"
    )
    assert len(rows) == 5
    assert rows[0]["code"] == sand
    assert rows[1]["unit"] == "Ton"
    assert Decimal(rows[1]["quantity"]) == Decimal(cement)
    assert Decimal(rows[2]["quantity"]) == Decimal(water)
    assert [row["code"] for row in rows[3:]] == ["10.100.1062", "10.100.1062"]
    assert analysis["approval_allowed"] is False
    assert analysis["read_only"] is True


@pytest.mark.external_pdf
def test_resource_totals_without_extra_markup(analysis):
    expected = Decimal(EXPECTED[analysis["position_code"]][4])
    assert Decimal(analysis["total"]) == expected
    assert sum(Decimal(row["amount"]) for row in analysis["resources"]) == expected
    assert analysis["additional_overhead_applied"] is False


@pytest.mark.external_pdf
def test_evidence_matches_original_extracted_page(analysis):
    text = analysis["source"]["page_text"]
    spans = [row["evidence"] for row in analysis["resources"]]
    spans.extend([analysis["analysis_evidence"], analysis["total_evidence"]])
    for span in spans:
        assert 0 <= span["start"] < span["end"] <= len(text)
        assert text[span["start"]:span["end"]] == span["quote"]
        assert span["pdf_page"] == analysis["source"]["pdf_page"]


@pytest.mark.external_pdf
def test_changed_resource_amount_is_rejected(analysis):
    text = analysis["source"]["page_text"]
    span = analysis["resources"][0]["evidence"]
    original_amount = analysis["resources"][0]["amount"].replace(".", ",")
    changed_amount = format(Decimal(analysis["resources"][0]["amount"]) + 1, ".2f").replace(".", ",")
    before, after = span["quote"].rsplit(original_amount, 1)
    damaged = text[:span["start"]] + before + changed_amount + after + text[span["end"]:]
    with pytest.raises(ValueError, match="arithmetic mismatch"):
        parse_auxiliary_text(damaged, analysis["position_code"])


@pytest.mark.external_pdf
def test_missing_resource_cannot_be_filled_from_adjacent_analysis(analysis):
    text = analysis["source"]["page_text"]
    span = analysis["resources"][2]["evidence"]
    damaged = text[:span["start"]] + text[span["end"]:]
    with pytest.raises(ValueError, match="resources"):
        parse_auxiliary_text(damaged, analysis["position_code"])


def test_general_mortar_code_is_not_accepted_as_fine_mortar():
    with pytest.raises(ValueError, match="Unsupported"):
        parse_auxiliary_text("", "19.100.2505")


def test_unverified_source_is_rejected(tmp_path):
    path = tmp_path / "wrong-source.pdf"
    path.write_bytes(b"Unverified source")
    with pytest.raises(ValueError, match="SHA-256"):
        read_auxiliary_analysis(path, "19.100.2506")


@pytest.mark.parametrize("code", ["19.100.2504", "19.100.2508"])
@pytest.mark.external_pdf
def test_auxiliary_price_matches_parent_resource_price(code):
    parent_path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    auxiliary_path = os.environ.get("ARKEMX_AUXILIARY_PDF")
    assert parent_path and auxiliary_path, "Both PDF source paths must be set"
    parent = read_analysis(parent_path)
    auxiliary = read_auxiliary_analysis(auxiliary_path, code)
    rows = [row for row in parent["resources"] if row["code"] == code]
    assert len(rows) == 1
    assert rows[0]["unit"] == auxiliary["unit"]
    assert Decimal(rows[0]["unit_price"]) == Decimal(auxiliary["total"])
    assert parent["source"]["price_date"] == auxiliary["source"]["price_date"]
