
"""A2.4 - Layer-specific cement dosage safety tests."""

from app.technical_analysis.comparator import compare_layers


def test_second_layer_dosage_mismatch():
    metraj = (
        "250 kg cimento dozlu harc ile 20 mm kaba siva "
        "uzerine 350 kg cimento dozlu harc ile 8 mm ince siva"
    )
    catalog = (
        "250 kg cimento dozlu harc ile 20 mm kaba siva "
        "uzerine 300 kg cimento dozlu harc ile 8 mm ince siva"
    )

    result = compare_layers(metraj, catalog)

    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False
    assert (
        "LAYER_2_CEMENT_DOSAGE_KG_MISMATCH"
        in result["blockers"]
    )


def test_swapped_layer_dosages_are_not_equivalent():
    metraj = (
        "250 kg cimento dozlu harc ile 20 mm kaba siva "
        "uzerine 350 kg cimento dozlu harc ile 8 mm ince siva"
    )
    catalog = (
        "350 kg cimento dozlu harc ile 20 mm kaba siva "
        "uzerine 250 kg cimento dozlu harc ile 8 mm ince siva"
    )

    result = compare_layers(metraj, catalog)

    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False

    assert (
        "LAYER_1_CEMENT_DOSAGE_KG_MISMATCH"
        in result["blockers"]
    )
    assert (
        "LAYER_2_CEMENT_DOSAGE_KG_MISMATCH"
        in result["blockers"]
    )


def test_identical_multilayer_dosages_are_not_ambiguous():
    description = (
        "250 kg cimento dozlu harc ile 20 mm kaba siva "
        "uzerine 350 kg cimento dozlu harc ile 8 mm ince siva"
    )

    result = compare_layers(description, description)

    assert result["approval_allowed"] is False
    assert not result["blockers"]
    assert (
        "CEMENT_DOSAGE_KG_AMBIGUOUS"
        not in result["review_flags"]
    )
