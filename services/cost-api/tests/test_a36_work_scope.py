"""Application exclusions remain explicit and never become positive layers."""

import pytest

from app.technical_analysis.comparator import compare_layers
from app.technical_analysis.layers import extract_layer_measurements

POSITIVE = "20 mm cimento kaba siva; 8 mm cimento ince siva yapilmasi"


@pytest.mark.parametrize("side", ["metraj", "catalog"])
@pytest.mark.parametrize("phrase", [
    "ince siva yapilmayacak",
    "8 mm cimento ince siva yapilmayacak",
    "8 mm cimento ince siva haric",
    "ince siva yapilmasi haric",
    "ince siva dahil degildir",
    "ince siva uygulanmayacaktir",
])
def test_excluded_application_blocks_positive_scope(side, phrase):
    negative = f"20 mm cimento kaba siva; {phrase}"
    left, right = (negative, POSITIVE) if side == "metraj" else (POSITIVE, negative)
    result = compare_layers(left, right)
    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False
    checks = [c for c in result["technical_checks"] if c["field"] == "work_scope_ince_siva"]
    assert len(checks) == 1
    check = checks[0]
    assert check["status"] == "block"
    assert check[f"{side}_value"] == "excluded"
    other = "catalog" if side == "metraj" else "metraj"
    assert check[f"{other}_value"] == "included"
    assert "WORK_SCOPE_INCE_SIVA_MISMATCH" in result["blockers"]
    assert all(layer["work_type"] != "ince_siva" for layer in result[f"{side}_layers"])
    for key, text in (("metraj", left), ("catalog", right)):
        for evidence in check[f"{key}_evidence"]:
            assert text[evidence["start"]:evidence["end"]] == evidence["quote"]


def test_missing_opposite_scope_is_review_not_inferred_inclusion():
    result = compare_layers("20 mm kaba siva; ince siva haric", "20 mm kaba siva")
    checks = [c for c in result["technical_checks"] if c["field"] == "work_scope_ince_siva"]
    assert len(checks) == 1
    assert checks[0]["status"] == "review"
    assert checks[0]["catalog_value"] is None
    assert result["status"] == "review"


def test_conflicting_scope_requires_review():
    text = "20 mm kaba siva; ince siva dahil; ince siva haric"
    result = compare_layers(text, POSITIVE)
    checks = [c for c in result["technical_checks"] if c["field"] == "work_scope_ince_siva"]
    assert checks[0]["status"] == "review"
    assert checks[0]["metraj_value"] is None
    assert result["approval_allowed"] is False


def test_boya_exclusion_does_not_exclude_plaster():
    layers = extract_layer_measurements("20 mm cimento kaba siva boya haric")
    assert len(layers) == 1
    assert layers[0].work_type == "kaba_siva"


def test_double_negation_is_not_a_positive_layer():
    text = "8 mm cimento ince siva haric degil"
    assert extract_layer_measurements(text) == ()
    result = compare_layers(text, POSITIVE)
    checks = [c for c in result["technical_checks"] if c["field"] == "work_scope_ince_siva"]
    assert checks[0]["status"] == "review"
    assert checks[0]["metraj_value"] is None
