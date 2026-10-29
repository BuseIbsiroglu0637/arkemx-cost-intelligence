"""Named layers retain known properties when thickness is absent."""

from decimal import Decimal

import pytest

from app.technical_analysis.comparator import compare_layers
from app.technical_analysis.layers import extract_layer_measurements


def description(missing):
    coarse = "" if "coarse" in missing else "20 mm "
    fine = "" if "fine" in missing else "8 mm "
    return (
        f"250 kg cimento dozlu harcla {coarse}kaba siva uzerine "
        f"350 kg cimento dozlu harcla {fine}ince siva"
    )


@pytest.mark.parametrize("side", ["metraj", "catalog"])
@pytest.mark.parametrize("missing", [("coarse",), ("fine",), ("coarse", "fine")])
def test_known_properties_survive_missing_thickness(side, missing):
    incomplete = description(missing)
    complete = description(())
    left, right = (
        (incomplete, complete) if side == "metraj" else (complete, incomplete)
    )
    result = compare_layers(left, right)

    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    assert len(result["metraj_layers"]) == len(result["catalog_layers"]) == 2

    for index, kind in enumerate(("coarse", "fine")):
        layer = result[f"{side}_layers"][index]
        assert layer["work_type"] == ("kaba_siva" if index == 0 else "ince_siva")
        assert layer["materials"] == ["cimento"]
        if kind in missing:
            assert layer["thickness_mm"] is None
        else:
            assert Decimal(layer["thickness_mm"]) == (20 if index == 0 else 8)

    for check in result["checks"]:
        missing_thickness = (
            check["field"] == "thickness_mm"
            and ("coarse", "fine")[check["layer"] - 1] in missing
        )
        assert check["status"] == ("review" if missing_thickness else "match")
        if missing_thickness:
            assert check[f"{side}_value"] is None

    dosages = [
        check for check in result["technical_checks"]
        if check["field"] == "cement_dosage_kg"
    ]
    assert len(dosages) == 2
    assert [check["metraj_value"] for check in dosages] == ["250", "350"]
    assert [check["catalog_value"] for check in dosages] == ["250", "350"]
    assert all(check["status"] == "match" for check in dosages)


def test_both_sources_missing_thickness_never_match():
    text = description(("coarse", "fine"))
    result = compare_layers(text, text)
    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    thickness = [c for c in result["checks"] if c["field"] == "thickness_mm"]
    assert len(thickness) == 2
    assert all(c["status"] == "review" for c in thickness)
    assert all(c["metraj_value"] is None and c["catalog_value"] is None for c in thickness)


def test_original_evidence_offsets_for_unmeasured_layer():
    text = "  20 mm çimento esaslı kaba sıva üzerine\n alçı esaslı ince sıva  "
    layers = extract_layer_measurements(text)
    assert len(layers) == 2
    assert layers[1].work_type == "ince_siva"
    assert layers[1].materials == ("alci",)
    assert layers[1].thickness_mm is None
    for layer in layers:
        assert text[layer.start:layer.end] == layer.quote


def test_material_only_clause_does_not_create_layer():
    layers = extract_layer_measurements("20 mm kaba siva; boya haric; cimento dahildir")
    assert len(layers) == 1


def test_excluded_unmeasured_layer_is_not_positive_application():
    layers = extract_layer_measurements("20 mm kaba siva; ince siva yapilmayacak")
    assert len(layers) == 1


def test_ambiguous_unmeasured_applications_are_unresolved():
    layers = extract_layer_measurements("cimento kaba siva ve alci ince siva")
    assert len(layers) == 1
    assert layers[0].thickness_mm is None
    assert layers[0].work_type is None
    assert layers[0].materials == ()
    result = compare_layers(layers[0].quote, layers[0].quote)
    assert result["status"] == "review"


def test_missing_thickness_does_not_hide_dosage_mismatch():
    left = description(("fine",)).replace("350 kg", "300 kg")
    result = compare_layers(left, description(()))
    assert result["status"] == "blocked"
    assert "LAYER_2_CEMENT_DOSAGE_KG_MISMATCH" in result["blockers"]
    assert result["approval_allowed"] is False
