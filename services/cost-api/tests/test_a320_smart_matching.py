"""A3.20: only evidence-backed automatic proposals; no silent cost approval."""
from decimal import Decimal
from types import SimpleNamespace

from app.a320_smart_matching import (
    enrich_technical,
    find_pdf_candidates,
    issue_summary,
    potential_plaster_pairs,
)


def item(identifier, description, quantity="168.50", unit="m²", row=2):
    return SimpleNamespace(
        id=identifier, source_row=row, raw_description=description,
        quantity=Decimal(quantity), normalized_unit=unit, review_required=False,
    )


def position(code, description, unit="m³"):
    return SimpleNamespace(id=code, description=description, unit=unit)


def test_equal_plaster_quantities_only_propose_a_review_not_a_merge():
    first = item("a", "20 mm çimento esaslı kaba sıva", row=3)
    second = item("b", "8 mm ince sıva uygulaması", row=4)
    pairs = potential_plaster_pairs([first, second])
    assert pairs == {"a": [4], "b": [3]}
    technical = enrich_technical("20 mm kaba sıva", "20 mm kaba sıva",
                                 {"status": "compatible", "blockers": [],
                                  "review_flags": []}, plaster_partner_rows=[4])
    assert technical["status"] == "review"
    assert "POSSIBLE_COMBINED_PLASTER_SCOPE" in technical["review_flags"]
    assert "birleşik" in issue_summary(first.raw_description, [], [4])


def test_different_quantities_or_known_surfaces_not_grouped():
    first = item("a", "Dış cephe 20 mm kaba sıva", row=2)
    second = item("b", "İç cephe 8 mm ince sıva", row=3)
    assert potential_plaster_pairs([first, second]) == {}
    assert potential_plaster_pairs([
        first, item("c", "8 mm ince sıva", quantity="170", row=4)
    ]) == {}


def test_concrete_class_is_not_replaced_by_similar_class():
    source = item("a", "C25/30 beton dökümü", quantity="18.4", unit="m³")
    pdf = [
        position("15.000.0001", "C30/37 hazır beton dökümü"),
        position("15.000.0002", "C25/30 hazır beton dökülmesi"),
    ]
    result = find_pdf_candidates(source, pdf)
    assert result[0]["position_id"] == "15.000.0002"
    check = enrich_technical(source.raw_description, pdf[0].description,
                             {"status": "compatible", "blockers": [],
                              "review_flags": []})
    assert check["status"] == "blocked"
    assert "CONCRETE_CLASS_MISMATCH" in check["blockers"]


def test_missing_concrete_class_is_review_not_false_compatibility():
    check = enrich_technical("C25/30 beton dökümü", "Beton dökülmesi",
                             {"status": "compatible", "blockers": [],
                              "review_flags": []})
    assert check["status"] == "review"
    assert "CONCRETE_CLASS_UNVERIFIED" in check["review_flags"]


def test_water_based_paint_requires_evidence():
    check = enrich_technical("İç cephe su bazlı boya uygulaması",
                             "İç cephe boyanması",
                             {"status": "compatible", "blockers": [],
                              "review_flags": []})
    assert check["status"] == "review"
    assert "PAINT_BASE_UNVERIFIED" in check["review_flags"]
    assert "Su bazlı" in issue_summary(
        "İç cephe su bazlı boya uygulaması",
        [{"review_flags": check["review_flags"],
          "blockers": check["blockers"], "technical_status": check["status"]}],
    )


def test_paint_fallback_retrieves_word_variants_without_inventing_a_code():
    source = item("a", "İç cephe su bazlı boya uygulaması", quantity="310")
    pdf = [position("15.100.0001", "İç cephe boyanması su esaslı boya", unit="m²")]
    result = find_pdf_candidates(source, pdf)
    assert result and result[0]["position_id"] == "15.100.0001"


def test_no_candidates_do_not_turn_into_fake_match():
    source = item("a", "İç cephe su bazlı boya uygulaması", quantity="310")
    result = find_pdf_candidates(source, [position("15.100.0001", "Beton dökümü")])
    assert not result
    assert "bulunamadı" in issue_summary(source.raw_description, result)
