"""Immutable, source-attributed small pilot costs."""
from alembic import op
import sqlalchemy as sa

revision = "0017_pilot_cost_snapshots"
down_revision = "0016_a331_pilot_technical_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("pilot_cost_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "request_key", name="uq_pilot_cost_request"))
    op.create_index("ix_pilot_cost_snapshots_project_id", "pilot_cost_snapshots", ["project_id"])


def downgrade():
    op.drop_table("pilot_cost_snapshots")
