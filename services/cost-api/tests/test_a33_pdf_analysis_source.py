"""A3.3.1 - Pinned PDF source and failure-path tests."""

import os
from decimal import Decimal

import pytest

from app.technical_analysis.pdf_analysis_source import (
    parse_analysis_text,
    read_analysis,
)


@pytest.fixture(scope="module")
def analysis():
    path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert path, "ARKEMX_ANALYSIS_PDF must be set"
    return read_analysis(path)


def test_source_identity_and_unit(analysis):
    assert analysis["position_code"] == "15.275.1111"
    assert analysis["unit"] == "m²"
    assert analysis["source"]["pdf_page"] == 423
    assert analysis["source"]["printed_page"] == 418
    assert analysis["source"]["sha256"] == (
        "81c814c4673af09bd295d1bc0a151ef2a1"
        "eee3a4f9ddc66754bf1410bb6ce1fa"
    )
    assert analysis["read_only"] is True
    assert analysis["approval_allowed"] is False


def test_resource_codes_exclude_main_position(analysis):
    codes = [item["code"] for item in analysis["resources"]]

    assert codes == [
        "19.100.2504",
        "19.100.2508",
        "10.130.9991",
        "10.100.1012",
        "10.100.1044",
        "10.100.1062",
        "10.100.1062",
    ]


def test_analysis_totals(analysis):
    totals = analysis["totals"]

    assert Decimal(totals["material_and_labor"]) == Decimal("595.60")
    assert Decimal(totals["overhead_and_profit"]) == Decimal("148.90")
    assert Decimal(totals["total"]) == Decimal("744.50")
    assert totals["currency"] == "TRY"


def test_all_evidence_matches_original_page_text(analysis):
    text = analysis["source"]["page_text"]
    spans = [
        item["evidence"]
        for item in analysis["resources"]
    ]
    spans.extend([
        analysis["technical_description"],
        analysis["totals"]["evidence"],
    ])

    for span in spans:
        assert 0 <= span["start"] < span["end"] <= len(text)
        assert text[span["start"]:span["end"]] == span["quote"]
        assert span["pdf_page"] == 423
        assert span["offset_basis"] == "extracted_page_text"


def test_missing_resource_is_rejected(analysis):
    text = analysis["source"]["page_text"]
    span = analysis["resources"][2]["evidence"]
    damaged = text[:span["start"]] + text[span["end"]:]

    with pytest.raises(ValueError, match="resource rows"):
        parse_analysis_text(damaged)


def test_incorrect_resource_amount_is_rejected(analysis):
    text = analysis["source"]["page_text"]
    span = analysis["resources"][0]["evidence"]
    assert "39,26" in span["quote"]

    changed_row = span["quote"].replace("39,26", "40,26", 1)
    damaged = (
        text[:span["start"]]
        + changed_row
        + text[span["end"]:]
    )

    with pytest.raises(ValueError, match="arithmetic mismatch"):
        parse_analysis_text(damaged)


def test_inconsistent_final_total_is_rejected(analysis):
    text = analysis["source"]["page_text"]
    span = analysis["totals"]["evidence"]
    assert "744,50" in span["quote"]

    changed_totals = span["quote"].replace("744,50", "745,50", 1)
    damaged = (
        text[:span["start"]]
        + changed_totals
        + text[span["end"]:]
    )

    with pytest.raises(ValueError, match="total is inconsistent"):
        parse_analysis_text(damaged)


def test_adjacent_position_cannot_supply_missing_resource(analysis):
    text = analysis["source"]["page_text"]
    first_water = analysis["resources"][2]["evidence"]
    damaged = text[:first_water["start"]] + text[first_water["end"]:]

    # The adjacent position still contains a water resource.
    assert "15.275.1112" in damaged
    assert "10.130.9991" in damaged

    # Its resource must not fill the missing target-position row.
    with pytest.raises(ValueError, match="resource rows"):
        parse_analysis_text(damaged)