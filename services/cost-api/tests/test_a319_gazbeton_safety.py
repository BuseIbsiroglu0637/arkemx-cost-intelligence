"""Gasbeton proposals must never hide unknown strength or density."""
from app.technical import compare, extract


METRAJ = "10 cm gazbeton duvar imalatı"
PDF = (
    "10 cm kalınlığındaki teçhizatsız gazbeton duvar blokları ile duvar yapılması "
    "(gazbeton tutkalı ile) (3,50 N/mm² ve 500 kg/m³)"
)


def test_missing_strength_and_density_require_review():
    result = compare(METRAJ, "m²", PDF, "m²")
    assert result["status"] == "review"
    assert result["manual_approval_allowed"] is False
    assert "GAZBETON_STRENGTH_N_MM2_UNVERIFIED" in result["review_flags"]
    assert "GAZBETON_DENSITY_KG_M3_UNVERIFIED" in result["review_flags"]


def test_explicit_matching_properties_can_pass_first_level():
    detail = METRAJ + " 3,50 N/mm² dayanım ve 500 kg/m³ yoğunluk"
    result = compare(detail, "m²", PDF, "m²")
    assert result["status"] == "compatible"
    assert not result["blockers"]
    assert "GAZBETON_STRENGTH_N_MM2_MATCH" in result["matches"]
    assert "GAZBETON_DENSITY_KG_M3_MATCH" in result["matches"]


def test_strength_conflict_blocks_candidate():
    detail = METRAJ + " 2,50 N/mm² dayanım ve 500 kg/m³ yoğunluk"
    result = compare(detail, "m²", PDF, "m²")
    assert result["status"] == "blocked"
    assert "GAZBETON_STRENGTH_N_MM2_MISMATCH" in result["blockers"]


def test_density_conflict_blocks_candidate():
    detail = METRAJ + " 3,50 N/mm² dayanım ve 400 kg/m³ yoğunluk"
    result = compare(detail, "m²", PDF, "m²")
    assert result["status"] == "blocked"
    assert "GAZBETON_DENSITY_KG_M3_MISMATCH" in result["blockers"]


def test_other_material_does_not_require_gazbeton_properties():
    result = compare("20 mm çimento sıva", "m²", "20 mm çimento sıva yapılması", "m²")
    assert not any("GAZBETON_" in flag for flag in result["review_flags"] + result["blockers"])
    assert extract("C25/30 beton dökümü")["gazbeton_density_kg_m3"] is None
