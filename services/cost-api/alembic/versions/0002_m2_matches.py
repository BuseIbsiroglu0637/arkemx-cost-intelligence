"""M2 match runs, candidate evidence and immutable human decisions.

Revision ID: 0002_m2_matches
Revises: 0001_m1_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_m2_matches"
down_revision = "0001_m1_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("match_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("catalog_versions.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("algorithm", sa.String(80), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_match_runs_project_id", "match_runs", ["project_id"])
    op.create_table("match_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("match_runs.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("position_id", sa.String(36), sa.ForeignKey("catalog_positions.id"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("similarity", sa.Numeric(5, 4), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("approvable", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("run_id", "work_item_id", "rank", name="uq_match_rank"))
    op.create_index("ix_match_candidates_run_id", "match_candidates", ["run_id"])
    op.create_index("ix_match_candidates_work_item_id", "match_candidates", ["work_item_id"])
    op.create_table("match_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("match_candidates.id"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("decided_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_match_decisions_candidate_id", "match_decisions", ["candidate_id"])


def downgrade():
    op.drop_index("ix_match_decisions_candidate_id", table_name="match_decisions")
    op.drop_table("match_decisions")
    op.drop_index("ix_match_candidates_work_item_id", table_name="match_candidates")
    op.drop_index("ix_match_candidates_run_id", table_name="match_candidates")
    op.drop_table("match_candidates")
    op.drop_index("ix_match_runs_project_id", table_name="match_runs")
    op.drop_table("match_runs")
