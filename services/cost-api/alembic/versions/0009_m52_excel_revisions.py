"""M5.2 explicit revised metraj lineage.

Revision ID: 0009_m52_excel_revisions
Revises: 0008_m5_cost_drafts
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_m52_excel_revisions"
down_revision = "0008_m5_cost_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "metraj_revision_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("baseline_import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("new_import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("baseline_estimate_id", sa.String(36), sa.ForeignKey("cost_estimates.id"), nullable=True),
        sa.Column("old_sha256", sa.String(64), nullable=False),
        sa.Column("new_sha256", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("new_import_id", name="uq_m52_new_import"),
    )
    op.create_index("ix_metraj_revision_events_organization_id", "metraj_revision_events", ["organization_id"])
    op.create_index("ix_metraj_revision_events_project_id", "metraj_revision_events", ["project_id"])


def downgrade():
    op.drop_index("ix_metraj_revision_events_project_id", table_name="metraj_revision_events")
    op.drop_index("ix_metraj_revision_events_organization_id", table_name="metraj_revision_events")
    op.drop_table("metraj_revision_events")
