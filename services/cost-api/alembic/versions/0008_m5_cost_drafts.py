"""M5 immutable draft cost estimates with explicit manual unit prices.

Revision ID: 0008_m5_cost_drafts
Revises: 0007_m43_bulk
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_m5_cost_drafts"
down_revision = "0007_m43_bulk"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cost_estimates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("match_runs.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("catalog_versions.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total", sa.Numeric(22, 2), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("catalog_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "request_key", name="uq_cost_estimate_request"),
        sa.CheckConstraint("currency = 'TRY'", name="ck_cost_currency"),
    )
    op.create_index("ix_cost_estimates_organization_id", "cost_estimates", ["organization_id"])
    op.create_index("ix_cost_estimates_project_id", "cost_estimates", ["project_id"])
    op.create_index("ix_cost_estimates_run_id", "cost_estimates", ["run_id"])
    op.create_table(
        "cost_estimate_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("estimate_id", sa.String(36), sa.ForeignKey("cost_estimates.id"), nullable=False),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("match_candidates.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("position_id", sa.String(36), sa.ForeignKey("catalog_positions.id"), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("position_code", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("amount", sa.Numeric(22, 2), nullable=False),
        sa.Column("price_source", sa.String(200), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("estimate_id", "candidate_id", name="uq_cost_line_candidate"),
        sa.UniqueConstraint("estimate_id", "work_item_id", name="uq_cost_line_item"),
        sa.CheckConstraint("quantity > 0 AND unit_price > 0 AND amount >= 0", name="ck_cost_positive"),
    )
    op.create_index("ix_cost_estimate_lines_estimate_id", "cost_estimate_lines", ["estimate_id"])


def downgrade():
    op.drop_index("ix_cost_estimate_lines_estimate_id", table_name="cost_estimate_lines")
    op.drop_table("cost_estimate_lines")
    op.drop_index("ix_cost_estimates_run_id", table_name="cost_estimates")
    op.drop_index("ix_cost_estimates_project_id", table_name="cost_estimates")
    op.drop_index("ix_cost_estimates_organization_id", table_name="cost_estimates")
    op.drop_table("cost_estimates")
