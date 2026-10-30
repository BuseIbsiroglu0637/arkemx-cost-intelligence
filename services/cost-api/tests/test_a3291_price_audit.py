"""A3.29.1: reconciliation of PDF source price and itemized input totals."""
from dataclasses import replace
from decimal import Decimal

from app.a318_pdf_engine import PdfPosition, verified_price_audit


def fixture(amounts=("238,03", "16,50", "195,30", "129,15")):
    return PdfPosition(
        id="15.225.1004",
        description="10 cm gazbeton duvar 2.50 N/mm2 400 kg/m3",
        unit="m²",
        price=Decimal("723.73"),
        price_verified=True,
        pdf_page=255,
        ingredients=tuple({"code": f"10.100.100{i}", "amount": value}
                          for i, value in enumerate(amounts)),
        scope="Ornek analiz tarifi",
    )


def test_pdf_price_audit_explains_existing_25_percent_check():
    audit = verified_price_audit(fixture())
    assert audit == {
        "inputs_total": "578.98",
        "reconciliation_addition_percent": 25,
        "reconciliation_addition": "144.75",
        "calculated_price": "723.73",
        "pdf_price": "723.73",
        "difference": "0.00",
        "status": "reconciled_to_pdf_with_parser_rule",
    }


def test_non_verified_or_inconsistent_price_is_not_presented_as_valid():
    base = fixture()
    assert verified_price_audit(replace(base, price_verified=False)) is None
    assert verified_price_audit(replace(base, price=Decimal("780.00"))) is None
    assert verified_price_audit(replace(base, ingredients=())) is None
    assert verified_price_audit(fixture(("238,03", "bilinmiyor"))) is None


def test_price_audit_does_not_reinterpret_source_amount_as_approved_cost():
    audit = verified_price_audit(fixture())
    assert audit is not None
    assert "approved" not in audit
    assert "official_current" not in audit
    assert audit["status"] == "reconciled_to_pdf_with_parser_rule"
