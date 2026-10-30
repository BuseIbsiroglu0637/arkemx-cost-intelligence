"""A3.23: grout spacing and 60x60 tile size are not tile thickness."""
from app.matching import dimensions, evaluate
from app.technical import compare, extract

METRAJ = "60x60 cm porselen seramik zemin kaplaması"
PDF = (
    "60 x 60 cm anma ebatlarında, rektifiyeli, her türlü renk, desen ve "
    "yüzey özelliğinde, I.kalite, mat, sırsız porselen karo ile "
    "3 mm derz aralıklı döşeme kaplaması yapılması (karo yapıştırıcısı ile)"
)


def test_actual_pdf_description_separates_three_measurements():
    result = extract(PDF, "m²")
    assert result["material"] == "seramik"
    assert result["dimensions"] == [[60, 60]]
    assert result["thickness_mm"] is None
    assert result["joint_width_mm"] == 3
    assert dimensions(PDF) == ({(60, 60)}, set())


def test_pdf_joint_width_does_not_trigger_missing_tile_thickness_warning():
    result = compare(METRAJ, "m²", PDF, "m²")
    assert "THICKNESS_MM_UNVERIFIED" not in result["review_flags"]
    assert "THICKNESS_MM_MISMATCH" not in result["blockers"]
    assert "JOINT_WIDTH_MM_UNVERIFIED" not in result["review_flags"]
    joint = next(item for item in result["fields"] if item["key"] == "joint_width_mm")
    assert joint["status"] == "not_specified"
    assert result["manual_approval_allowed"] is False or result["status"] == "compatible"


def test_matching_engine_does_not_mislabel_3mm_joint_as_tile_thickness():
    from types import SimpleNamespace

    item = SimpleNamespace(
        raw_description=METRAJ, quantity=42.75, normalized_unit="m²",
        review_required=False,
    )
    pos = SimpleNamespace(id="15.390.1008", description=PDF, unit="m²")
    result = evaluate(item, pos)
    assert result is not None
    assert "THICKNESS_NOT_SPECIFIED_IN_METRAJ" not in result["warnings"]
    assert "THICKNESS_MISMATCH" not in result["warnings"]


def test_explicit_tile_thickness_and_joint_spacing_are_both_extracted():
    phrase = "60x60 cm porselen karo, 8 mm kalınlığında, 3 mm derz aralıklı zemin kaplama"
    parsed = extract(phrase)
    assert parsed["dimensions"] == [[60, 60]]
    assert parsed["thickness_mm"] == 8
    assert parsed["joint_width_mm"] == 3


def test_joint_width_before_number_is_understood():
    parsed = extract("60 x 60 cm porselen karo ile derz aralığı 3 mm döşeme kaplama")
    assert parsed["dimensions"] == [[60, 60]]
    assert parsed["thickness_mm"] is None
    assert parsed["joint_width_mm"] == 3


def test_explicit_wrong_joint_width_blocks_candidate():
    required = METRAJ + " 5 mm derz aralığı"
    result = compare(required, "m²", PDF, "m²")
    assert result["status"] == "blocked"
    assert "JOINT_WIDTH_MM_MISMATCH" in result["blockers"]
    assert "THICKNESS_MM_MISMATCH" not in result["blockers"]


def test_explicit_tile_thickness_is_not_satisfied_by_joint_width():
    required = METRAJ + " 3 mm kalınlığında"
    result = compare(required, "m²", PDF, "m²")
    assert "THICKNESS_MM_UNVERIFIED" in result["review_flags"]
    assert "THICKNESS_MM_MATCH" not in result["matches"]
    assert result["status"] == "review"


def test_real_tile_thickness_conflict_remains_a_blocker():
    required = METRAJ + " 8 mm kalınlığında"
    candidate = PDF.replace("3 mm derz aralıklı", "9 mm kalınlığında ve 3 mm derz aralıklı")
    result = compare(required, "m²", candidate, "m²")
    assert result["status"] == "blocked"
    assert "THICKNESS_MM_MISMATCH" in result["blockers"]


def test_other_material_thickness_regression():
    assert extract("20 mm çimento esaslı kaba sıva")["thickness_mm"] == 20
    assert extract("10 cm gazbeton duvar")["thickness_mm"] == 100


def test_tile_size_with_spaces_never_becomes_600mm_thickness():
    data = extract("60 x 60 cm porselen seramik karo zemin kaplaması")
    assert data["dimensions"] == [[60, 60]]
    assert data["thickness_mm"] is None
