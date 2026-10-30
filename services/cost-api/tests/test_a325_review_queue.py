"""A3.25: missing technical facts remain pending; saved picks are never approval."""
from app.a325_review_queue import classify_row

BASE = {
    "description": "10 cm gazbeton duvar imalatı",
    "candidates": [],
    "saved_selection": None,
    "clarification": None,
    "related_excel_rows": [],
    "quantity_known": True,
    "unit_known": True,
    "input_review_required": False,
}


def state(**changes):
    return classify_row(**(BASE | changes))


def option(code="15.225.1004", status="compatible", flags=None, verified=True, shared=False):
    return {
        "code": code, "technical_status": status, "blockers": [],
        "review_flags": flags or [], "source_price_verified": verified,
        "possible_shared_scope": shared,
    }


def selected(code="15.225.1004", stale=False):
    return {"code": code if not stale else None, "current": not stale, "stale": stale}


def test_missing_gazbeton_strength_and_density_show_both_unknowns_even_if_saved():
    result = state(
        candidates=[option(flags=[
            "GAZBETON_STRENGTH_N_MM2_UNVERIFIED",
            "GAZBETON_DENSITY_KG_M3_UNVERIFIED",
        ], status="review")],
        saved_selection=selected(),
    )
    assert result["group"] == "needs_info"
    assert "Gazbeton dayanımı (N/mm²)" in result["missing_fields"]
    assert "Gazbeton yoğunluğu (kg/m³)" in result["missing_fields"]
    assert result["engineering_approved"] is False
    assert result["cost_allowed"] is False


def test_ceramic_finish_choice_does_not_automatically_verify_project_spec():
    result = state(
        description="60x60 porselen seramik kaplama",
        candidates=[option(code="15.390.1008", status="review")],
        saved_selection=selected("15.390.1008"),
        clarification={"key": "ceramic_finish", "options": [
            {"code": "15.390.1008", "label": "Mat, sırsız"},
            {"code": "15.385.1008", "label": "Beyaz, sırlı"},
        ]},
    )
    assert result["group"] == "needs_info"
    assert "Seramik türü (mimari şartname)" in result["missing_fields"]
    assert result["cost_allowed"] is False


def test_plaster_common_scope_never_prechecked_by_candidate_pick():
    result = state(
        description="20 mm kaba sıva", candidates=[option()],
        saved_selection=selected(), related_excel_rows=[4],
    )
    assert result["group"] == "needs_review"
    assert "Birleşik" in result["reason"]


def test_unrecorded_candidate_never_prechecked():
    result = state(candidates=[option()])
    assert result["group"] == "needs_review"


def test_no_candidates_requires_review_not_approval():
    result = state(candidates=[])
    assert result["group"] == "needs_review"
    assert result["cost_allowed"] is False


def test_stale_candidate_requires_review():
    result = state(candidates=[option()], saved_selection=selected(stale=True))
    assert result["group"] == "needs_review"
    assert "geçersiz" in result["reason"]


def test_unverified_price_never_prechecked():
    result = state(candidates=[option(verified=False)], saved_selection=selected())
    assert result["group"] == "needs_review"


def test_incomplete_quantity_remains_pending():
    result = state(candidates=[option()], saved_selection=selected(), quantity_known=False)
    assert result["group"] == "needs_info"


def test_technical_comparison_flags_keep_review_pending():
    result = state(candidates=[option(status="review", flags=["SCOPE_REVIEW_REQUIRED"])],
                   saved_selection=selected())
    assert result["group"] == "needs_review"


def test_only_fully_source_checked_saved_candidate_enters_precheck_bucket():
    result = state(candidates=[option()], saved_selection=selected())
    assert result["group"] == "prechecked"
    assert result["reason"] == "Kontrol edilen özellikler eşleşiyor"
    assert result["engineering_approved"] is False
    assert result["cost_allowed"] is False


def test_shared_scope_never_enters_prechecked():
    result = state(candidates=[option(shared=True)], saved_selection=selected())
    assert result["group"] == "needs_review"
