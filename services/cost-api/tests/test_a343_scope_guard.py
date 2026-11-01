"""A3.43: work operation outranks shared material tokens."""
from decimal import Decimal
from types import SimpleNamespace

from app.a343_work_scope import scope_blocker
from app.a318_pdf_engine import PdfPosition
from app.a318_pdf_api import _pdf_candidate_check


def item(description, unit="m²"):
    return SimpleNamespace(raw_description=description, normalized_unit=unit,
                           quantity=Decimal("3"), review_required=False)


def position(description, unit="m²"):
    return PdfPosition(
        id="15.999.9001", description=description, unit=unit,
        price=Decimal("125.00"), price_verified=True,
        pdf_page=42, scope="", ingredients=(),
    )


def test_material_and_demolition_do_not_match():
    left = "SERAMİK VISTA FLUME MAT 60X120 ZEMİN MALZEMESİ"
    right = "Seramik ve fayans kaplamanın sökülmesi"
    assert scope_blocker(left, right) == "WORK_SCOPE_DEMOLITION_MISMATCH"
    result = _pdf_candidate_check(item(left), position(right))
    assert result["status"] == "blocked"
    assert "WORK_SCOPE_DEMOLITION_MISMATCH" in result["blockers"]
    assert result["manual_approval_allowed"] is False


def test_labor_and_demolition_do_not_match():
    left = "PVC İŞÇİLİK (HER TÜRLÜ SARF MALZEME YÜKLENİCİYE AİTTİR)"
    right = "Alüminyum ve PVC kapı ve pencere doğramasının sökülmesi"
    assert scope_blocker(left, right) == "WORK_SCOPE_DEMOLITION_MISMATCH"
    result = _pdf_candidate_check(item(left), position(right))
    assert result["status"] == "blocked"


def test_separately_priced_material_is_not_mixed_installation():
    left = "60x120 seramik zemin malzemesi"
    right = "60x120 seramik zemin kaplaması yapılması"
    assert scope_blocker(left, right) == "WORK_SCOPE_MATERIAL_ONLY_MISMATCH"
    assert _pdf_candidate_check(item(left), position(right))["status"] == "blocked"


def test_labor_only_does_not_absorb_material_cost():
    left = "Seramik döşeme işçilik"
    right = "Seramik malzemesi dahil döşeme yapılması"
    assert scope_blocker(left, right) == "WORK_SCOPE_LABOR_ONLY_MISMATCH"


def test_legitimate_installation_is_not_blocked_by_scope():
    left = "60x120 seramik zemin kaplaması yapılması"
    right = "60x120 seramik zemin kaplaması yapılması"
    assert scope_blocker(left, right) is None
    assert _pdf_candidate_check(item(left), position(right))["status"] != "blocked"


def test_legitimate_demolition_is_not_blocked_by_scope():
    left = "Eski seramik kaplamanın sökülmesi"
    right = "Seramik ve fayans kaplamasının sökülmesi"
    assert scope_blocker(left, right) is None
