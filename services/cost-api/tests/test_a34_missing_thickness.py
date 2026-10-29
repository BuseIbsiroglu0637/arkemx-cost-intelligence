"""Missing layer thickness must be visible in comparison checks."""

from decimal import Decimal

import pytest

from app.technical_analysis.comparator import compare_layers

COMPLETE = (
    "20 mm cimento esasli kaba siva uzerine "
    "8 mm cimento esasli ince siva"
)

MISSING = (
    "20 mm cimento esasli kaba siva uzerine "
    "cimento esasli ince siva"
)


@pytest.mark.parametrize("missing_side", ["metraj", "catalog"])
def test_missing_second_layer_thickness_is_explicit(missing_side):
    left = MISSING if missing_side == "metraj" else COMPLETE
    right = MISSING if missing_side == "catalog" else COMPLETE

    result = compare_layers(left, right)

    assert result["status"] == "review"
    assert result["approval_allowed"] is False

    checks = [
        check
        for check in result["checks"]
        if check.get("layer") == 2
        and check["field"] == "thickness_mm"
    ]

    assert len(checks) == 1, (
        "Missing second-layer thickness must have an explicit check"
    )

    check = checks[0]
    assert check["status"] == "review"
    assert check[f"{missing_side}_value"] is None

    known_side = "catalog" if missing_side == "metraj" else "metraj"
    assert Decimal(check[f"{known_side}_value"]) == Decimal("8")