"""PDF-backed technical review API acceptance tests."""

import os
from uuid import uuid4

import pytest
from test_m41 import auth

from app.technical_analysis.pdf_analysis_source import read_analysis

URL = "/api/a3/compare-pdf"


def authorized_headers(client):
    return auth(
        client,
        "PDF Review Test Office",
        f"pdf-review-{uuid4().hex}@example.com",
    )


@pytest.fixture(scope="module")
def verified_analysis():
    path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert path, "ARKEMX_ANALYSIS_PDF must be set"
    return read_analysis(path)


def test_pdf_review_requires_authentication(client):
    response = client.post(
        URL,
        json={"metraj_description": "20 mm kaba sıva"},
    )

    assert response.status_code == 401


@pytest.mark.external_pdf
def test_pdf_review_returns_verified_source(client, verified_analysis):
    description = verified_analysis["technical_description"]["quote"]

    response = client.post(
        URL,
        headers=authorized_headers(client),
        json={"metraj_description": description},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    analysis = data["catalog_analysis"]

    assert data["read_only"] is True
    assert data["approval_allowed"] is False
    assert data["comparison"]["approval_allowed"] is False
    assert data["sources"]["catalog"] == description
    assert analysis["position_code"] == "15.275.1111"
    assert analysis["source"]["sha256"] == (
        verified_analysis["source"]["sha256"]
    )
    assert analysis["source"]["pdf_page"] == 423
    assert analysis["source"]["price_date"] == "2026-01-01"
    assert analysis["totals"]["total"] == "744.50"
    assert len(analysis["resources"]) == 7
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.external_pdf
def test_pdf_review_blocks_changed_dosage(client, verified_analysis):
    description = verified_analysis["technical_description"]["quote"]
    assert description.count("350 kg") == 1

    response = client.post(
        URL,
        headers=authorized_headers(client),
        json={
            "metraj_description": description.replace(
                "350 kg", "300 kg", 1
            ),
        },
    )

    assert response.status_code == 200, response.text
    comparison = response.json()["comparison"]

    assert comparison["status"] == "blocked"
    assert comparison["approval_allowed"] is False

    dosage_checks = [
        check
        for check in comparison["technical_checks"]
        if check["field"] == "cement_dosage_kg"
    ]

    assert len(dosage_checks) == 2
    assert dosage_checks[1]["metraj_value"] == "300"
    assert dosage_checks[1]["catalog_value"] == "350"
    assert dosage_checks[1]["status"] == "block"


def test_pdf_review_rejects_unconfigured_source(client, monkeypatch):
    monkeypatch.delenv("ARKEMX_ANALYSIS_PDF", raising=False)

    response = client.post(
        URL,
        headers=authorized_headers(client),
        json={"metraj_description": "20 mm kaba sıva"},
    )

    assert response.status_code == 503
    assert "comparison" not in response.json()
    assert "catalog_analysis" not in response.json()


def test_pdf_review_rejects_wrong_source(client, monkeypatch, tmp_path):
    wrong_source = tmp_path / "wrong-source.pdf"
    wrong_source.write_bytes(b"This is not the verified source PDF.")

    monkeypatch.setenv("ARKEMX_ANALYSIS_PDF", str(wrong_source))

    response = client.post(
        URL,
        headers=authorized_headers(client),
        json={"metraj_description": "20 mm kaba sıva"},
    )

    assert response.status_code == 503
    assert "comparison" not in response.json()
    assert "catalog_analysis" not in response.json()


def test_pdf_review_rejects_client_supplied_path(client):
    response = client.post(
        URL,
        headers=authorized_headers(client),
        json={
            "metraj_description": "20 mm kaba sıva",
            "pdf_path": "some-other-file.pdf",
        },
    )

    assert response.status_code == 422