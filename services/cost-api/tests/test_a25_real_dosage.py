"""A2.5 - Cement dosage checks using a real analysis passage.

Reference: 15.275.1111, 2026 analysis PDF, page 423.
These tests use text; they do not parse the PDF.
"""

from app.technical_analysis.comparator import compare_layers


def real_description(second_dosage: int = 350) -> str:
    return (
        "1 m³ dişli kuma 250 kg çimento katılması ile "
        "hazırlanan harçla ortalama 2 cm kalınlığında "
        "kaba sıva yapılması, üzerine 1 m³ mil kumuna "
        f"{second_dosage} kg çimento ilavesiyle "
        "hazırlanan harçla ortalama 0,8 cm kalınlığında "
        "ince sıva yapılması"
    )


def dosage_checks(result: dict) -> list[dict]:
    checks = [
        check
        for check in result["technical_checks"]
        if check["field"] == "cement_dosage_kg"
    ]

    assert len(checks) == 2, (
        "Expected a cement dosage check for each layer."
    )

    return sorted(checks, key=lambda check: check["layer"])


def test_real_description_has_two_layer_dosages():
    text = real_description()

    result = compare_layers(text, text)
    checks = dosage_checks(result)

    assert [check["layer"] for check in checks] == [1, 2]
    assert [check["metraj_value"] for check in checks] == [
        "250",
        "350",
    ]
    assert [check["catalog_value"] for check in checks] == [
        "250",
        "350",
    ]
    assert all(check["status"] == "match" for check in checks)

    assert not result["blockers"]
    assert result["approval_allowed"] is False


def test_real_second_layer_dosage_mismatch_blocks():
    metraj = real_description(second_dosage=350)
    catalog = real_description(second_dosage=300)

    result = compare_layers(metraj, catalog)
    checks = dosage_checks(result)

    assert checks[0]["status"] == "match"
    assert checks[1]["status"] == "block"
    assert checks[1]["metraj_value"] == "350"
    assert checks[1]["catalog_value"] == "300"

    assert result["status"] == "blocked"
    assert (
        "LAYER_2_CEMENT_DOSAGE_KG_MISMATCH"
        in result["blockers"]
    )
    assert result["approval_allowed"] is False


def test_real_dosage_evidence_belongs_to_its_layer():
    text = real_description()

    result = compare_layers(text, text)
    checks = dosage_checks(result)

    for check in checks:
        layer_index = check["layer"] - 1

        for side in ("metraj", "catalog"):
            evidence_items = check[f"{side}_evidence"]
            layer = result[f"{side}_layers"][layer_index]
            layer_evidence = layer["evidence"]

            assert len(evidence_items) == 1
            evidence = evidence_items[0]

            assert (
                layer_evidence["start"]
                <= evidence["start"]
                < evidence["end"]
                <= layer_evidence["end"]
            )
            assert (
                text[evidence["start"]:evidence["end"]]
                == evidence["quote"]
            )
            assert evidence["offset_basis"] == "original_text"

    first_quote = checks[0]["metraj_evidence"][0]["quote"]
    second_quote = checks[1]["metraj_evidence"][0]["quote"]

    assert "250 kg" in first_quote
    assert "350 kg" not in first_quote
    assert "350 kg" in second_quote
    assert "250 kg" not in second_quote
