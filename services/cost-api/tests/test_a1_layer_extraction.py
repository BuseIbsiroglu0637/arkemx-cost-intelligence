"""A1.2 - Technical layer extraction regression tests."""

from decimal import Decimal

from app.technical_analysis.layers import extract_layer_measurements


def test_wall_and_plaster_have_separate_thicknesses():
    text = "10 cm gazbeton duvar, 2 cm siva"

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert result[0].thickness_mm == Decimal("100")
    assert result[0].work_type == "gazbeton_duvar"
    assert result[1].thickness_mm == Decimal("20")
    assert result[1].work_type == "siva"


def test_two_plaster_layers_are_separate():
    text = (
        "20 mm cimento esasli kaba siva uzerine "
        "8 mm cimento esasli ince siva"
    )

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert result[0].work_type == "kaba_siva"
    assert result[0].thickness_mm == Decimal("20")
    assert result[1].work_type == "ince_siva"
    assert result[1].thickness_mm == Decimal("8")


def test_second_layer_material_is_preserved():
    text = (
        "20 mm cimento esasli kaba siva uzerine "
        "8 mm alci esasli ince siva"
    )

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert result[0].materials == ("cimento",)
    assert result[1].materials == ("alci",)


def test_source_quotes_match_original_text():
    text = "2 cm kaba siva, 0,8 cm ince siva"

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert [item.thickness_mm for item in result] == [
        Decimal("20"),
        Decimal("8"),
    ]

    for item in result:
        assert 0 <= item.start < item.end <= len(text)
        assert text[item.start:item.end] == item.quote


def test_a12_material_before_thickness():
    text = (
        "Cimento esasli 2 cm kaba siva uzerine "
        "alci esasli 0,5 cm ince siva"
    )

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert result[0].work_type == "kaba_siva"
    assert result[0].thickness_mm == Decimal("20")
    assert result[0].materials == ("cimento",)
    assert result[1].work_type == "ince_siva"
    assert result[1].thickness_mm == Decimal("5")
    assert result[1].materials == ("alci",)


def test_a12_real_2026_plaster_analysis():
    """Reference: 15.275.1111, PDF page 423."""

    text = (
        "1 m³ dişli kuma 250 kg çimento katılması ile "
        "hazırlanan harçla ortalama 2 cm kalınlığında "
        "kaba sıva yapılması, üzerine 1 m³ mil kumuna "
        "350 kg çimento ilavesiyle hazırlanan harçla "
        "ortalama 0,8 cm kalınlığında ince sıva yapılması"
    )

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert result[0].thickness_mm == Decimal("20")
    assert result[0].work_type == "kaba_siva"
    assert result[0].materials == ("cimento",)
    assert result[1].thickness_mm == Decimal("8")
    assert result[1].work_type == "ince_siva"
    assert result[1].materials == ("cimento",)

    assert "250 kg" in result[0].quote
    assert "350 kg" in result[1].quote
    assert "350 kg" not in result[0].quote

    for item in result:
        assert 0 <= item.start < item.end <= len(text)
        assert text[item.start:item.end] == item.quote


def test_turkish_characters_preserve_original_source():
    text = (
        "ÇİMENTO esaslı 2 CM kaba sıva ÜZERİNE "
        "ALÇI esaslı 0,8 CM ince sıva"
    )

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert result[0].work_type == "kaba_siva"
    assert result[0].materials == ("cimento",)
    assert result[0].thickness_mm == Decimal("20")
    assert result[1].work_type == "ince_siva"
    assert result[1].materials == ("alci",)
    assert result[1].thickness_mm == Decimal("8")

    assert "ÇİMENTO" in result[0].quote
    assert "ALÇI" not in result[0].quote
    assert "ALÇI" in result[1].quote

    for item in result:
        assert 0 <= item.start < item.end <= len(text)
        assert text[item.start:item.end] == item.quote


def test_cm_and_mm_have_equivalent_values():
    in_cm = extract_layer_measurements(
        "2 cm cimento esasli kaba siva"
    )
    in_mm = extract_layer_measurements(
        "20 mm cimento esasli kaba siva"
    )

    assert len(in_cm) == 1
    assert len(in_mm) == 1
    assert in_cm[0].thickness_mm == Decimal("20")
    assert in_cm[0].thickness_mm == in_mm[0].thickness_mm
    assert in_cm[0].work_type == in_mm[0].work_type
    assert in_cm[0].materials == in_mm[0].materials


def test_multiple_measures_without_separator_remain_unresolved():
    text = "20 mm cimento kaba siva 8 mm alci ince siva"

    result = extract_layer_measurements(text)

    assert len(result) == 2
    assert [item.thickness_mm for item in result] == [
        Decimal("20"),
        Decimal("8"),
    ]

    for item in result:
        assert item.work_type is None
        assert item.materials == ()
        assert 0 <= item.start < item.end <= len(text)
        assert text[item.start:item.end] == item.quote