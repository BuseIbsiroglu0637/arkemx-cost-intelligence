"""A2.5 - Unsupported or ambiguous dosage must require review."""

import pytest

from app.technical_analysis.comparator import compare_layers


@pytest.mark.parametrize(
    "description",
    [
        pytest.param(
            "250 kg cimento katilmasi ile 20 mm kaba siva",
            id="missing-sand-volume",
        ),
        pytest.param(
            "2 m\u00b3 disli kuma 250 kg cimento "
            "katilmasi ile 20 mm kaba siva",
            id="unsupported-two-cubic-metres",
        ),
        pytest.param(
            "1 m\u00b3 disli kuma 250 kg cimento "
            "eklenerek 20 mm kaba siva",
            id="unrecognized-addition-expression",
        ),
        pytest.param(
            "1 m\u00b3 disli kuma, 250 kg cimento "
            "katilmasi ile 20 mm kaba siva",
            id="sand-basis-outside-layer-evidence",
        ),
        pytest.param(
            "1 m\u00b3 disli kuma ve 1 m\u00b3 mil kumuna "
            "250 kg cimento katilmasi ile 20 mm kaba siva",
            id="multiple-sand-bases",
        ),
        pytest.param(
            "1 m\u00b3 disli kuma 250 kg cimento katilmasi "
            "ve 300 kg cimento ilavesiyle 20 mm kaba siva",
            id="conflicting-dosages-in-one-layer",
        ),
    ],
)
def test_uncertain_dosage_requires_review(description):
    result = compare_layers(description, description)

    # Identical wording does not resolve uncertainty.
    assert result["status"] == "review"
    assert result["approval_allowed"] is False
    assert result["review_flags"]

    checks = [
        check
        for check in result["technical_checks"]
        if check["field"] == "cement_dosage_kg"
    ]

    assert checks
    assert all(check["status"] == "review" for check in checks)
