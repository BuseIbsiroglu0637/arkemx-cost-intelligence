"""Verify PDF technical descriptions through the comparison engine."""

import os
from decimal import Decimal

import pytest

from app.technical_analysis.comparator import compare_layers
from app.technical_analysis.pdf_analysis_source import read_analysis


@pytest.fixture(scope="module")
def catalog_description():
    path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert path, "ARKEMX_ANALYSIS_PDF must be set"

    analysis = read_analysis(path)
    return analysis["technical_description"]["quote"]


def test_pdf_description_preserves_two_thicknesses(catalog_description):
    result = compare_layers(catalog_description, catalog_description)

    for side in ("metraj_layers", "catalog_layers"):
        layers = result[side]

        assert len(layers) == 2
        assert layers[0]["work_type"] == "kaba_siva"
        assert Decimal(layers[0]["thickness_mm"]) == Decimal("20")
        assert layers[1]["work_type"] == "ince_siva"
        assert Decimal(layers[1]["thickness_mm"]) == Decimal("8")

    assert result["approval_allowed"] is False


def test_pdf_description_preserves_layer_dosages(catalog_description):
    result = compare_layers(catalog_description, catalog_description)

    checks = [
        check
        for check in result["technical_checks"]
        if check["field"] == "cement_dosage_kg"
    ]

    assert len(checks) == 2
    assert [check["metraj_value"] for check in checks] == ["250", "350"]
    assert [check["catalog_value"] for check in checks] == ["250", "350"]
    assert all(check["status"] == "match" for check in checks)
    assert result["approval_allowed"] is False


def test_changed_fine_plaster_dosage_is_blocked(catalog_description):
    assert catalog_description.count("350 kg") == 1
    changed_description = catalog_description.replace(
        "350 kg", "300 kg", 1
    )

    result = compare_layers(
        changed_description,
        catalog_description,
    )

    checks = [
        check
        for check in result["technical_checks"]
        if check["field"] == "cement_dosage_kg"
    ]

    assert len(checks) == 2
    assert checks[0]["status"] == "match"
    assert checks[1]["metraj_value"] == "300"
    assert checks[1]["catalog_value"] == "350"
    assert checks[1]["status"] == "block"
    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False