"""Verify migration 0003 can resume a partly upgraded SQLite database.

Alembic migration scripts must not assume that SQLite DDL rolled back when the
revision marker still points at 0002.
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("partial", [False, True])
def test_m21_sqlite_migration_can_start_fresh_or_resume_partially(partial):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0003_m21_revisions.py"
    spec = importlib.util.spec_from_file_location("m21_repair_test", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE match_runs (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE work_items (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO match_runs (id) VALUES ('existing-run')")
        if partial:
            # Old Alembic op.add_column added this column but then failed trying
            # to apply a separate SQLite FK constraint.
            conn.exec_driver_sql(
                "ALTER TABLE match_runs ADD COLUMN parent_run_id VARCHAR(36)"
            )
        operations = Operations(MigrationContext.configure(conn))
        with patch.object(migration, "op", operations):
            migration.upgrade()
            columns = {col["name"] for col in sa.inspect(conn).get_columns("match_runs")}
            assert "parent_run_id" in columns
            assert "changed_item_count" in columns
            assert sa.inspect(conn).has_table("work_item_revisions")
            assert sa.inspect(conn).has_table("match_run_item_snapshots")
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM match_runs").scalar() == 1
            # If migration resumes from some later sub-step, indexes also survive.
            migration.upgrade()
            assert len(sa.inspect(conn).get_indexes("match_run_item_snapshots")) == 2
    engine.dispose()
