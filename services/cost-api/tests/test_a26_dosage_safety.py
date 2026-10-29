
"""A2.6 - Cement dosage ambiguity and safety regressions."""

from app.technical_analysis.comparator import compare_layers


def test_conflicting_dosages_in_same_layer():
    text = (
        "250 kg cimento dozlu harc ve "
        "350 kg cimento dozlu harc ile "
        "20 mm kaba siva"
    )

    result = compare_layers(text, text)

    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    assert (
        "CEMENT_DOSAGE_KG_AMBIGUOUS"
        in result["review_flags"]
    )


def test_two_cubic_metres_not_equivalent_to_one():
    metraj = (
        "1 m³ dişli kuma 250 kg çimento katılması "
        "ile 2 cm kaba sıva"
    )
    catalog = (
        "2 m³ dişli kuma 250 kg çimento katılması "
        "ile 2 cm kaba sıva"
    )

    result = compare_layers(metraj, catalog)

    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    assert (
        "CEMENT_DOSAGE_KG_UNASSIGNED"
        in result["review_flags"]
    )


def test_unrecognized_cement_expression_requires_review():
    metraj = (
        "250 kg cimento karistirilarak "
        "20 mm kaba siva"
    )
    catalog = (
        "250 kg cimento dozlu harc ile "
        "20 mm kaba siva"
    )

    result = compare_layers(metraj, catalog)

    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    assert (
        "CEMENT_DOSAGE_KG_UNASSIGNED"
        in result["review_flags"]
    )


def test_matching_known_sand_basis_is_not_ambiguous():
    text = (
        "1 m³ dişli kuma 250 kg çimento katılması "
        "ile 2 cm kaba sıva"
    )

    result = compare_layers(text, text)

    assert result["status"] == "layer_match"
    assert result["approval_allowed"] is False
    assert not result["blockers"]
    assert not result["review_flags"]
