
"""A3.6 - Source-preserving cost scenario regression tests."""

import copy
import os

import pytest

from app.technical_analysis.cost_scenario import (
    calculate_300kg_scenario,
)
from app.technical_analysis.pdf_analysis_source import (
    read_analysis,
)


@pytest.fixture(scope="module")
def source_analysis():
    path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert path, "ARKEMX_ANALYSIS_PDF is required"
    return read_analysis(path)


def test_scenario_calculation(source_analysis):
    result = calculate_300kg_scenario(source_analysis)

    assert result["original"]["total_tl"] == "744.50"

    assert result["replacement"]["resource_code"] == (
        "19.100.2506"
    )
    assert result["replacement"]["quantity"] == "0.010"
    assert result["replacement"]["line_amount_tl"] == "19.26"

    scenario = result["scenario"]

    assert scenario["subtotal_tl"] == "594.32"
    assert scenario["overhead_tl"] == "148.58"
    assert scenario["total_tl"] == "742.90"
    assert scenario["difference_tl"] == "-1.60"


def test_original_analysis_is_not_modified(source_analysis):
    before = copy.deepcopy(source_analysis)

    calculate_300kg_scenario(source_analysis)

    assert source_analysis == before
    assert source_analysis["totals"]["total"] == "744.50"


@pytest.mark.parametrize(
    ("code", "unit", "price"),
    [
        ("19.100.2508", "m³", "1926.15"),
        ("19.100.2507", "m³", "1926.15"),
        ("19.100.2506", "Sa", "1926.15"),
        ("19.100.2506", "m³", "2054.48"),
        ("19.100.2506", "m³", "NaN"),
    ],
)
def test_unsupported_alternatives_are_rejected(
    source_analysis,
    code,
    unit,
    price,
):
    with pytest.raises(ValueError):
        calculate_300kg_scenario(
            source_analysis,
            alternative_code=code,
            alternative_unit=unit,
            alternative_unit_price=price,
        )


def test_wrong_original_resource_is_rejected(source_analysis):
    changed = copy.deepcopy(source_analysis)

    for row in changed["resources"]:
        if row["code"] == "19.100.2508":
            row["code"] = "19.100.2507"

    with pytest.raises(ValueError):
        calculate_300kg_scenario(changed)


def test_changed_pdf_identity_is_rejected(source_analysis):
    changed = copy.deepcopy(source_analysis)
    changed["source"]["sha256"] = "invalid"

    with pytest.raises(ValueError):
        calculate_300kg_scenario(changed)


def test_changed_source_amount_is_rejected(source_analysis):
    changed = copy.deepcopy(source_analysis)

    for row in changed["resources"]:
        if row["code"] == "19.100.2508":
            row["amount"] = "21.54"

    with pytest.raises(ValueError):
        calculate_300kg_scenario(changed)


def test_scenario_cannot_grant_approval(source_analysis):
    result = calculate_300kg_scenario(source_analysis)

    assert result["read_only"] is True
    assert result["approval_allowed"] is False

    assert result["technical_compatibility"] == "not_evaluated"

    assert result["alternative_price_verification"] == (
        "pending_source_document"
    )

    assert result["assumptions"]["quantity_fixed"] is True
    assert result["assumptions"]["overhead_applied_once"] is True


# Requires the actual private source documents, never a fabricated substitute.
pytestmark = pytest.mark.external_pdf
