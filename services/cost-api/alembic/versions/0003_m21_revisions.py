"""M2.1 append-only metraj revisions and match input snapshots.

Revision ID: 0003_m21_revisions
Revises: 0002_m2_matches
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_m21_revisions"
down_revision = "0002_m2_matches"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("match_runs",
        sa.Column("parent_run_id", sa.String(36), sa.ForeignKey("match_runs.id"), nullable=True))
    op.add_column("match_runs",
        sa.Column("changed_item_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("work_item_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("corrected_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("work_item_id", "revision", name="uq_item_revision"))
    op.create_index("ix_work_item_revisions_work_item_id", "work_item_revisions", ["work_item_id"])
    op.create_table("match_run_item_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("match_runs.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("work_item_revisions.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit", sa.String(30), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("run_id", "work_item_id", name="uq_run_item_snapshot"))
    op.create_index("ix_match_run_item_snapshots_run_id", "match_run_item_snapshots", ["run_id"])
    op.create_index("ix_match_run_item_snapshots_work_item_id", "match_run_item_snapshots", ["work_item_id"])


def downgrade():
    op.drop_index("ix_match_run_item_snapshots_work_item_id", table_name="match_run_item_snapshots")
    op.drop_index("ix_match_run_item_snapshots_run_id", table_name="match_run_item_snapshots")
    op.drop_table("match_run_item_snapshots")
    op.drop_index("ix_work_item_revisions_work_item_id", table_name="work_item_revisions")
    op.drop_table("work_item_revisions")
    op.drop_column("match_runs", "changed_item_count")
    op.drop_column("match_runs", "parent_run_id")
