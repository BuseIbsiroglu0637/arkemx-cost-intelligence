
"""A2.1 - Layer comparison safety tests."""

from app.technical_analysis.comparator import compare_layers


def test_different_plaster_thickness_is_blocked():
    result = compare_layers(
        "10 cm gazbeton duvar, 2 cm siva",
        "10 cm gazbeton duvar, 5 cm siva",
    )

    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False
    assert "LAYER_2_THICKNESS_MM_MISMATCH" in result["blockers"]


def test_second_layer_thickness_is_blocked():
    result = compare_layers(
        "20 mm cimento kaba siva uzerine 8 mm cimento ince siva",
        "20 mm cimento kaba siva uzerine 12 mm cimento ince siva",
    )

    assert result["status"] == "blocked"
    assert "LAYER_2_THICKNESS_MM_MISMATCH" in result["blockers"]


def test_second_layer_material_is_blocked():
    result = compare_layers(
        "20 mm cimento kaba siva uzerine 8 mm cimento ince siva",
        "20 mm cimento kaba siva uzerine 8 mm alci ince siva",
    )

    assert result["status"] == "blocked"
    assert "LAYER_2_MATERIALS_MISMATCH" in result["blockers"]


def test_unresolved_measurements_require_review():
    text = "20 mm cimento kaba siva 8 mm alci ince siva"

    result = compare_layers(text, text)

    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    assert result["review_flags"]


def test_layer_count_difference_requires_review():
    result = compare_layers(
        "20 mm cimento kaba siva uzerine 8 mm cimento ince siva",
        "20 mm cimento kaba siva",
    )

    assert result["status"] == "review"
    assert "LAYER_COUNT_UNVERIFIED" in result["review_flags"]


def test_matching_layers_do_not_grant_approval():
    metraj = (
        "20 mm cimento kaba siva uzerine "
        "8 mm cimento ince siva"
    )
    catalog = (
        "2 cm cimento kaba siva uzerine "
        "0,8 cm cimento ince siva"
    )

    result = compare_layers(metraj, catalog)

    assert result["status"] == "layer_match"
    assert result["approval_allowed"] is False
    assert not result["blockers"]

    for check in result["checks"]:
        index = check["layer"] - 1

        left = check["metraj_evidence"]
        right = check["catalog_evidence"]

        assert metraj[left["start"]:left["end"]] == left["quote"]
        assert catalog[right["start"]:right["end"]] == right["quote"]

        assert result["metraj_layers"][index]["evidence"] == left
        assert result["catalog_layers"][index]["evidence"] == right
