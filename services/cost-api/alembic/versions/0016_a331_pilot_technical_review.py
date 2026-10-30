"""A3.31: source-bound pilot acceptance, never qualified engineer approval."""
import sqlalchemy as sa
from alembic import op

revision = "0016_a331_pilot_technical_review"
down_revision = "0015_a330_analysis_engineer_signoff"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "a331_pilot_technical_review_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("analysis_revision_id", sa.String(36), sa.ForeignKey("a330_analysis_revisions.id"), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("work_item_id", "sequence", name="uq_a331_pilot_item_sequence"),
        sa.UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a331_pilot_request"),
        sa.CheckConstraint("sequence > 0", name="ck_a331_pilot_sequence"),
        sa.CheckConstraint("action IN ('accept','reopen')", name="ck_a331_pilot_action"),
    )
    for field in ("organization_id", "project_id", "work_item_id"):
        op.create_index(
            f"ix_a331_pilot_technical_review_events_{field}",
            "a331_pilot_technical_review_events", [field],
        )


def downgrade():
    op.drop_table("a331_pilot_technical_review_events")
