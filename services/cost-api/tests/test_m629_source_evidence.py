
"""M6.0-A.29 - Source evidence tests."""

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from app.pdf_catalog_parser import ParsedRow
from app.pdf_catalog_evidence import (
    create_position_evidence,
    sha256_file,
)


def sample_evidence():
    record = ParsedRow(
        code="TEST.001",
        description="Sentetik poz",
        unit="Sa",
        price=Decimal("310.00"),
        source_page=8,
    )

    return create_position_evidence(
        record,
        source_bbox=(44.8, 125.5, 560.0, 134.0),
        page_size=(595.5, 842.25),
        source_sha256="a" * 64,
        catalog_year=2026,
        catalog_period="2026-01",
        record_type="rayic",
    )


def test_valid_source_evidence():
    evidence = sample_evidence()

    assert evidence.source_page == 8
    assert evidence.validation_status == "needs_review"
    assert evidence.record_type == "rayic"


def test_invalid_document_hash():
    evidence = sample_evidence()

    with pytest.raises(ValueError):
        replace(evidence, source_sha256="invalid")


def test_bbox_outside_page_rejected():
    evidence = sample_evidence()

    with pytest.raises(ValueError):
        replace(
            evidence,
            source_bbox=(44.8, 125.5, 999.0, 134.0),
        )


def test_catalog_period_must_match_year():
    evidence = sample_evidence()

    with pytest.raises(ValueError):
        replace(evidence, catalog_period="2025-01")


def test_no_automatic_approval():
    evidence = sample_evidence()

    with pytest.raises(ValueError):
        replace(evidence, validation_status="approved")


def test_file_sha256(tmp_path):
    file = tmp_path / "synthetic.bin"
    file.write_bytes(b"ARKEMX synthetic test")

    expected = hashlib.sha256(
        b"ARKEMX synthetic test"
    ).hexdigest()

    assert sha256_file(file) == expected
