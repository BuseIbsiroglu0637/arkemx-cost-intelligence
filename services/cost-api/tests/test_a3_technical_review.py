
"""A3.1 - Authenticated technical comparison API tests."""

from uuid import uuid4

import pytest
from sqlalchemy import event
from test_m41 import auth

from app import a3_technical_review
from app.database import get_db
from app.main import app

URL = "/api/a3/compare"


def payload():
    return {
        "metraj_description": "10 cm gazbeton duvar, 2 cm siva",
        "catalog_description": "10 cm gazbeton duvar, 5 cm siva",
    }


def authorized_headers(client):
    return auth(
        client,
        "Synthetic A3 Test Office",
        f"a3-{uuid4().hex}@example.com",
    )


def test_a3_route_is_registered():
    assert URL in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"][URL]


def test_a3_requires_authentication(client):
    response = client.post(URL, json=payload())
    assert response.status_code == 401


def test_a3_blocks_technical_mismatch(client):
    response = client.post(
        URL,
        json=payload(),
        headers=authorized_headers(client),
    )

    assert response.status_code == 200, response.text

    data = response.json()
    comparison = data["comparison"]

    assert data["read_only"] is True
    assert comparison["status"] == "blocked"
    assert comparison["approval_allowed"] is False

    assert (
        "LAYER_2_THICKNESS_MM_MISMATCH"
        in comparison["blockers"]
    )

    assert response.headers["cache-control"] == "private, no-store"


def test_a3_evidence_offsets_are_correct(client):
    response = client.post(
        URL,
        json=payload(),
        headers=authorized_headers(client),
    )

    assert response.status_code == 200, response.text
    data = response.json()

    for check in data["comparison"]["checks"]:
        for side in ("metraj", "catalog"):
            evidence = check[f"{side}_evidence"]
            text = data["sources"][side]

            assert text[
                evidence["start"]:evidence["end"]
            ] == evidence["quote"]


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "metraj_description": " ",
            "catalog_description": "20 mm kaba siva",
        },
        {
            "metraj_description": "20 mm kaba siva",
            "catalog_description": " ",
        },
        {
            **payload(),
            "unexpected_field": "not allowed",
        },
        {
            "metraj_description": "A" * 5001,
            "catalog_description": "20 mm kaba siva",
        },
    ],
)
def test_a3_rejects_invalid_inputs(client, invalid_payload):
    response = client.post(
        URL,
        json=invalid_payload,
        headers=authorized_headers(client),
    )

    assert response.status_code == 422, response.text

def test_a3_preview_performs_no_database_writes(client):
    headers = authorized_headers(client)

    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    engine = db.get_bind()
    statements = []

    def capture(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        statements.append(statement.strip().lower())

    event.listen(engine, "before_cursor_execute", capture)

    try:
        response = client.post(
            URL,
            json=payload(),
            headers=headers,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        generator.close()

    assert response.status_code == 200, response.text
    assert statements
    assert all(
        statement.startswith("select")
        for statement in statements
    ), statements


def test_a3_rejects_engine_approval_permission(client, monkeypatch):
    headers = authorized_headers(client)

    monkeypatch.setattr(
        a3_technical_review,
        "compare_layers",
        lambda *args: {"approval_allowed": True},
    )

    response = client.post(
        URL,
        json=payload(),
        headers=headers,
    )

    assert response.status_code == 500
    assert "comparison" not in response.json()
