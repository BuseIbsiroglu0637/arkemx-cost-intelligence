"""A0 - Multilayer technical matching safety regressions."""

from app.evidence_v41 import analyze


def compare(metraj: str, catalog: str) -> dict:
    return analyze(
        metraj,
        "m\u00b2",
        catalog,
        "m\u00b2",
        quantity_known=True,
        review_required=False,
    )


def assert_not_approvable(result: dict) -> None:
    assert result["approval_allowed"] is False, (
        "Unsafe approval: "
        f"status={result['status']}, "
        f"basic_fields={result.get('basic_fields')}"
    )
    assert result["status"] in {"blocked", "review"}


def test_a01_wall_same_plaster_thickness_different():
    result = compare(
        "10 cm gazbeton duvar, 2 cm siva, malzeme dahil",
        "10 cm gazbeton duvar, 5 cm siva, malzeme dahil",
    )
    assert_not_approvable(result)


def test_a02_first_layer_same_second_layer_different():
    result = compare(
        "Dis cephede 20 mm cimento esasli kaba siva "
        "uzerine 8 mm cimento esasli ince siva, malzeme dahil",
        "Dis cephede 20 mm cimento esasli kaba siva "
        "uzerine 12 mm cimento esasli ince siva, malzeme dahil",
    )
    assert_not_approvable(result)


def test_a03_same_thickness_different_second_material():
    result = compare(
        "Dis cephede 20 mm cimento esasli kaba siva "
        "uzerine 8 mm cimento esasli ince siva, malzeme dahil",
        "Dis cephede 20 mm cimento esasli kaba siva "
        "uzerine 8 mm alci esasli ince siva, malzeme dahil",
    )
    assert_not_approvable(result)


def test_a04_identical_description_not_blocked():
    description = (
        "Ic duvarda 20 mm cimento esasli kaba siva, "
        "malzeme dahil"
    )
    result = compare(description, description)

    assert result["status"] != "blocked"
    assert not result["blockers"]
