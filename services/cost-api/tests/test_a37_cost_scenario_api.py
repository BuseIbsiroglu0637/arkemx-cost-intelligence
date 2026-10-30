
"""A3.7 - Cost scenario API safety tests."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from test_m41 import auth

from app.main import app

URL = "/api/a3/cost-scenario"

VALID = {
    "alternative_resource_code": "19.100.2506",
}


def headers(client):
    return auth(
        client,
        "Synthetic A37 Office",
        f"a37-{uuid4().hex}@example.com",
    )


def test_route_registered():
    assert URL in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"][URL]


def test_authentication_required(client):
    response = client.post(URL, json=VALID)
    assert response.status_code == 401


@pytest.mark.external_pdf
def test_verified_scenario_response(client):
    path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert path and Path(path).is_file()

    response = client.post(
        URL,
        json=VALID,
        headers=headers(client),
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"

    data = response.json()
    scenario = data["scenario"]

    assert data["read_only"] is True
    assert data["approval_allowed"] is False

    assert scenario["original"]["total_tl"] == "744.50"
    assert scenario["scenario"]["total_tl"] == "742.90"
    assert scenario["scenario"]["difference_tl"] == "-1.60"

    assert scenario["technical_compatibility"] == "not_evaluated"
    assert scenario["alternative_price_verification"] == (
        "verified_source_document"
    )

    alternative = scenario["alternative_price_source"]

    assert alternative["position_code"] == "19.100.2506"
    assert alternative["unit_price_tl"] == "1926.15"
    assert alternative["source"]["pdf_page"] == 697
    assert alternative["source"]["sha256"] == (
        "ca7453f9e8d583e28bb16130b19487"
        "edc8308831017d8d7e4daa0367c8038431"
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"alternative_resource_code": "19.100.2508"},
        {
            "alternative_resource_code": "19.100.2506",
            "unit_price_tl": "0.01",
        },
    ],
)
def test_invalid_requests_rejected(client, invalid):
    response = client.post(
        URL,
        json=invalid,
        headers=headers(client),
    )
    assert response.status_code == 422


def test_missing_pdf_configuration_rejected(client, monkeypatch):
    token_headers = headers(client)
    monkeypatch.delenv("ARKEMX_ANALYSIS_PDF", raising=False)

    response = client.post(
        URL,
        json=VALID,
        headers=token_headers,
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"

def test_missing_alternative_pdf_rejected(
    client,
    monkeypatch,
):
    token_headers = headers(client)
    monkeypatch.delenv("ARKEMX_ALT_PDF", raising=False)

    response = client.post(
        URL,
        json=VALID,
        headers=token_headers,
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == (
        "private, no-store"
    )


def test_modified_alternative_pdf_rejected(
    client,
    monkeypatch,
    tmp_path,
):
    token_headers = headers(client)

    altered = tmp_path / "modified.pdf"
    altered.write_bytes(b"%PDF-1.4\ninvalid source")

    monkeypatch.setenv("ARKEMX_ALT_PDF", str(altered))

    response = client.post(
        URL,
        json=VALID,
        headers=token_headers,
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == (
        "private, no-store"
    )
