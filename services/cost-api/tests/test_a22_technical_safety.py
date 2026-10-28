
"""A2.2 - Critical technical difference regression tests."""

import pytest

from app.technical_analysis.comparator import compare_layers


@pytest.mark.parametrize(
    ("metraj", "catalog", "case"),
    [
        (
            "250 kg cimento dozlu harc ile 20 mm kaba siva",
            "350 kg cimento dozlu harc ile 20 mm kaba siva",
            "different_mortar_dosage",
        ),
        (
            "Ic cephede 20 mm cimento esasli kaba siva",
            "Dis cephede 20 mm cimento esasli kaba siva",
            "different_environment",
        ),
        (
            "20 mm cimento kaba siva, malzeme dahil",
            "20 mm cimento kaba siva, malzeme haric",
            "different_material_scope",
        ),
    ],
)
def test_critical_difference_requires_review_or_block(
    metraj,
    catalog,
    case,
):
    result = compare_layers(metraj, catalog)

    assert result["status"] in {"blocked", "review"}, (
        f"Unsafe layer match in {case}: {result}"
    )

    assert result["approval_allowed"] is False
    assert result["blockers"] or result["review_flags"]


def test_reversed_layer_order_is_blocked():
    result = compare_layers(
        "20 mm cimento kaba siva uzerine "
        "8 mm cimento ince siva",
        "8 mm cimento ince siva uzerine "
        "20 mm cimento kaba siva",
    )

    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False
    assert result["blockers"]


@pytest.mark.parametrize(
    ("metraj", "catalog", "expected_code"),
    [
        (
            "250 kg cimento dozlu harc ile 20 mm kaba siva",
            "350 kg cimento dozlu harc ile 20 mm kaba siva",
            "CEMENT_DOSAGE_KG_MISMATCH",
        ),
        (
            "Ic cephede 20 mm cimento esasli kaba siva",
            "Dis cephede 20 mm cimento esasli kaba siva",
            "ENVIRONMENT_MISMATCH",
        ),
        (
            "20 mm cimento kaba siva, malzeme dahil",
            "20 mm cimento kaba siva, malzeme haric",
            "MATERIAL_SCOPE_MISMATCH",
        ),
    ],
)
def test_critical_difference_has_source_evidence(
    metraj,
    catalog,
    expected_code,
):
    result = compare_layers(metraj, catalog)

    assert result["status"] == "blocked"
    assert result["approval_allowed"] is False
    assert expected_code in result["blockers"]

    matching = [
        check
        for check in result["technical_checks"]
        if check["code"] == expected_code
    ]

    assert len(matching) == 1

    check = matching[0]
    assert check["status"] == "block"

    for side, source_text in (
        ("metraj", metraj),
        ("catalog", catalog),
    ):
        evidence_items = check[f"{side}_evidence"]

        assert evidence_items

        for evidence in evidence_items:
            start = evidence["start"]
            end = evidence["end"]

            assert 0 <= start < end <= len(source_text)
            assert source_text[start:end] == evidence["quote"]
            assert evidence["offset_basis"] == "original_text"
