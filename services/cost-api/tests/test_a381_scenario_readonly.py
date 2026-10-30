
"""A3.8.1 - Scenario API must not modify the test database."""
import pytest


import os
from pathlib import Path

from sqlalchemy import event

from app.database import get_db
from app.main import app

URL = "/api/a3/cost-scenario"
PAYLOAD = {"alternative_resource_code": "19.100.2506"}


def test_scenario_endpoint_performs_no_database_writes(
    client,
    auth,
):
    pdf_path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    assert pdf_path and Path(pdf_path).is_file()

    # The auth fixture creates the test user before observation.
    # Inspect only the isolated test database.
    dependency = app.dependency_overrides[get_db]
    generator = dependency()
    session = next(generator)
    engine = session.get_bind()
    generator.close()

    write_statements = []

    def observe_sql(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        sql = statement.lstrip().upper()

        if sql.startswith((
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "REPLACE ",
            "CREATE ",
            "ALTER ",
            "DROP ",
        )):
            write_statements.append(statement)

    with engine.connect() as connection:
        before = connection.exec_driver_sql(
            "SELECT total_changes()"
        ).scalar_one()

    event.listen(engine, "before_cursor_execute", observe_sql)

    try:
        for _ in range(2):
            response = client.post(
                URL,
                headers=auth,
                json=PAYLOAD,
            )

            assert response.status_code == 200, response.text

            result = response.json()
            assert result["read_only"] is True
            assert result["approval_allowed"] is False
            assert result["scenario"]["scenario"]["total_tl"] == "742.90"

    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            observe_sql,
        )

    with engine.connect() as connection:
        after = connection.exec_driver_sql(
            "SELECT total_changes()"
        ).scalar_one()

    assert before == after, "Database write counter changed"
    assert not write_statements, write_statements


# Requires the actual private source documents, never a fabricated substitute.
pytestmark = pytest.mark.external_pdf
