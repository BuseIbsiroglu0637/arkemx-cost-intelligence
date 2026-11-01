"""A3.42: manual poz requests are deferred until matched to an exact uploaded PDF."""
from alembic import op
import sqlalchemy as sa

revision = "0017_a342_manual_position_requests"
down_revision = "0016_a331_pilot_technical_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "a342_manual_position_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("work_item_revisions.id"), nullable=True),
        sa.Column("position_code", sa.String(80), nullable=False),
        sa.Column("recorded_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("work_item_id", name="uq_a342_manual_work_item"),
    )
    for field in ("organization_id", "project_id", "work_item_id"):
        op.create_index(
            f"ix_a342_manual_position_requests_{field}",
            "a342_manual_position_requests", [field],
        )


def downgrade():
    op.drop_table("a342_manual_position_requests")
