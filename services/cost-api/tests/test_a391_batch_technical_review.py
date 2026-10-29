"""Synthetic mixed-row acceptance pilot plus a real PDF integration check."""

import os
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.technical_analysis import batch_technical_review as pilot
from app.technical_analysis.support_registry import get_position_support

REFERENCE = (
    "Dış cephede 250 kg çimento dozlu 20 mm kaba sıva üzerine "
    "350 kg çimento dozlu 8 mm ince sıva"
)


def make_row(index=1, **changes):
    row = pilot.PilotRow(
        work_item_id=f"item-{index}",
        import_id="import-test",
        sheet_name="Metraj",
        source_row=index + 1,
        original_description=REFERENCE,
        description=REFERENCE,
        quantity="10",
        unit="m²",
        candidate_code="15.275.1111",
    )
    if "description" in changes and "original_description" not in changes:
        changes["original_description"] = changes["description"]
    return replace(row, **changes)


@pytest.fixture
def verified_reader(monkeypatch):
    """Synthetic source for service tests; not proof of actual PDF identity."""
    calls = []
    analysis = {
        "position_code": "15.275.1111",
        "unit": "m²",
        "read_only": True,
        "approval_allowed": False,
        "technical_description": {"quote": REFERENCE},
        "totals": {"total": "744.50", "currency": "TRY"},
        "source": {
            "filename": "synthetic.pdf",
            "pdf_page": 423,
            "sha256": "synthetic-test-source",
            "price_date": "2026-01-01",
        },
    }

    def reader(path):
        calls.append(path)
        return deepcopy(analysis)

    monkeypatch.setattr(pilot, "read_analysis", reader)
    return calls


# Twelve independently identified rows exercise the existing comparator.
CASES = [
    ({}, "checked_features_match", "verified"),
    ({"description": REFERENCE.replace("8 mm", "5 mm")}, "incompatible", "verified"),
    (
        {"description": REFERENCE.replace("350 kg", "300 kg")},
        "incompatible",
        "verified",
    ),
    (
        {"description": REFERENCE.replace("Dış cephede", "İç cephede")},
        "incompatible",
        "verified",
    ),
    (
        {"description": REFERENCE.replace("350 kg çimento", "350 kg alçı")},
        "incompatible",
        "verified",
    ),
    ({"description": REFERENCE.replace("8 mm ", "")}, "review_required", "verified"),
    (
        {
            "description": "Dış cephede çimento esaslı kaba sıva üzerine çimento esaslı ince sıva"
        },
        "review_required",
        "verified",
    ),
    ({"unit": "m³"}, "incompatible", "verified"),
    (
        {"candidate_code": "15.540.9999", "description": "İç duvar boyası"},
        "out_of_scope",
        "not_available",
    ),
    ({"candidate_code": None}, "review_required", "not_available"),
    ({"input_review_required": True}, "review_required", "verified"),
    ({"quantity": None}, "review_required", "verified"),
]


def test_twelve_row_pilot_preserves_every_identity_and_status(verified_reader):
    rows = tuple(make_row(i + 1, **changes) for i, (changes, _, _) in enumerate(CASES))
    before = deepcopy(rows)
    result = pilot.review_rows(rows, pdf_path="synthetic.pdf")
    assert len(result["rows"]) == result["row_count"] == 12
    assert rows == before
    assert len(verified_reader) == 1
    for source, record, (_, technical, price) in zip(
        rows, result["rows"], CASES, strict=True
    ):
        assert record["identity"]["work_item_id"] == source.work_item_id
        assert record["identity"]["import_id"] == source.import_id
        assert record["identity"]["source_row"] == source.source_row
        assert record["identity"]["sheet_name"] == source.sheet_name
        assert record["technical_status"] == technical
        assert record["price_source_status"] == price
        assert record["approval_allowed"] is False
        assert record["cost_scenario"] is None
    assert sum(result["technical_counts"].values()) == 12
    assert result["approval_allowed"] is False
    assert result["read_only"] is True


def test_verified_price_does_not_hide_technical_mismatch(verified_reader):
    row = make_row(description=REFERENCE.replace("350 kg", "300 kg"))
    result = pilot.review_rows((row,), pdf_path="synthetic.pdf")["rows"][0]
    assert result["technical_status"] == "incompatible"
    assert result["source_price"]["value"] == "744.50"
    assert result["price_source_status"] == "verified"
    assert (
        result["source_price"]["applicability"] == "not_authorized_for_metraj_costing"
    )


def test_comparison_evidence_refers_to_effective_description(verified_reader):
    result = pilot.review_rows((make_row(),), pdf_path="synthetic.pdf")["rows"][0]
    comparison = result["comparison"]
    for record, text in (
        (comparison["metraj_layers"], result["effective_description"]),
        (comparison["catalog_layers"], REFERENCE),
    ):
        for layer in record:
            span = layer["evidence"]
            assert text[span["start"] : span["end"]] == span["quote"]


def test_missing_source_is_reported_for_every_supported_row():
    result = pilot.review_rows((make_row(1), make_row(2)), pdf_path=None)
    for row in result["rows"]:
        assert row["price_source_status"] == "not_configured"
        assert row["technical_status"] == "review_required"
        assert row["source_price"] is None


def test_unverified_source_is_not_a_price(monkeypatch):
    def broken_reader(_path):
        raise ValueError("Wrong hash")

    monkeypatch.setattr(pilot, "read_analysis", broken_reader)
    result = pilot.review_rows((make_row(),), pdf_path="wrong.pdf")["rows"][0]
    assert result["price_source_status"] == "unverified"
    assert result["source_price"] is None
    assert result["comparison"] is None


def test_unsupported_code_does_not_read_source(verified_reader):
    row = make_row(candidate_code="19.100.2506")
    assert get_position_support(row.candidate_code) is None
    result = pilot.review_rows((row,), pdf_path="synthetic.pdf")
    assert not verified_reader
    assert result["rows"][0]["technical_status"] == "out_of_scope"


@pytest.mark.parametrize("size", [0, 21])
def test_batch_limits_are_explicit(size):
    with pytest.raises(ValueError, match="1 to 20"):
        pilot.review_rows(tuple(make_row(i) for i in range(size)), pdf_path=None)


def test_duplicate_item_is_rejected():
    row = make_row()
    with pytest.raises(ValueError, match="Duplicate"):
        pilot.review_rows((row, row), pdf_path=None)


def test_revision_identity_and_original_are_preserved(verified_reader):
    original = SimpleNamespace(
        id="item-1",
        import_id="import-test",
        source_row=9,
        raw_description="Özgün eksik tarif",
    )
    effective = SimpleNamespace(
        id=original.id,
        import_id=original.import_id,
        source_row=9,
        raw_description=REFERENCE,
        quantity="10",
        normalized_unit="m²",
        revision_id="revision-2",
        review_required=False,
    )
    row = pilot.row_from_effective_item(
        original, effective, sheet_name="Metraj", candidate_code="15.275.1111"
    )
    result = pilot.review_rows((row,), pdf_path="synthetic.pdf")["rows"][0]
    assert result["identity"]["revision_id"] == "revision-2"
    assert result["original_description"] == "Özgün eksik tarif"
    assert result["effective_description"] == REFERENCE
    assert original.raw_description == "Özgün eksik tarif"


def test_changed_description_requires_revision():
    row = replace(make_row(), description="Değişmiş tarif")
    with pytest.raises(ValueError, match="revision"):
        pilot.review_rows((row,), pdf_path=None)


def test_unknown_comparison_cannot_look_like_match(verified_reader, monkeypatch):
    monkeypatch.setattr(
        pilot,
        "compare_layers",
        lambda *_args: {
            "status": "unexpected",
            "approval_allowed": False,
        },
    )
    row = pilot.review_rows((make_row(),), pdf_path="synthetic.pdf")["rows"][0]
    assert row["technical_status"] == "review_required"
    assert "COMPARISON_UNVERIFIED" in row["flags"]


def test_real_pdf_reader_integration():
    path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert path, "ARKEMX_ANALYSIS_PDF must be set for real PDF integration"
    result = pilot.review_rows((make_row(),), pdf_path=path)["rows"][0]
    assert result["price_source_status"] == "verified"
    assert result["source_price"]["value"] == "744.50"
    assert result["comparison"] is not None
    assert result["source_price"]["source"]["pdf_page"] == 423
    assert result["approval_allowed"] is False


def test_distinct_ids_cannot_duplicate_same_excel_row():
    first = make_row()
    second = replace(first, work_item_id="different-id")
    with pytest.raises(ValueError, match="Duplicate Excel"):
        pilot.review_rows((first, second), pdf_path=None)


def test_explicit_exclusion_cannot_be_shown_as_match(verified_reader):
    row = make_row(
        description=(
            "Dış cephede 250 kg çimento dozlu 20 mm kaba sıva; ince sıva hariç"
        )
    )
    result = pilot.review_rows((row,), pdf_path="synthetic.pdf")["rows"][0]
    assert result["technical_status"] == "incompatible"
    assert result["price_source_status"] == "verified"
    assert result["approval_allowed"] is False


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-1", "1,234"])
def test_unverified_quantities_do_not_look_ready(verified_reader, quantity):
    result = pilot.review_rows(
        (make_row(quantity=quantity),), pdf_path="synthetic.pdf"
    )["rows"][0]
    assert result["technical_status"] == "review_required"
    assert "QUANTITY_UNVERIFIED" in result["flags"]
