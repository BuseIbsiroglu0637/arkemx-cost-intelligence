"""M5.2.1 operator queue-cancel ledger and excluded source registration.

Revision ID: 0010_m521_safe_queue
Revises: 0009_m52_excel_revisions
"""
from alembic import op
import sqlalchemy as sa
revision = "0010_m521_safe_queue"
down_revision = "0009_m52_excel_revisions"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "metraj_import_exclusions",
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("excluded_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_metraj_import_exclusions_organization_id",
        "metraj_import_exclusions", ["organization_id"])
    op.create_index("ix_metraj_import_exclusions_project_id",
        "metraj_import_exclusions", ["project_id"])
    op.create_table(
        "m43_queue_control_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("bulk_jobs.id"), unique=True, nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("import_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_m43_queue_control_events_organization_id",
        "m43_queue_control_events", ["organization_id"])
    op.create_index("ix_m43_queue_control_events_project_id",
        "m43_queue_control_events", ["project_id"])


def downgrade():
    op.drop_index("ix_m43_queue_control_events_project_id", table_name="m43_queue_control_events")
    op.drop_index("ix_m43_queue_control_events_organization_id", table_name="m43_queue_control_events")
    op.drop_table("m43_queue_control_events")
    op.drop_index("ix_metraj_import_exclusions_project_id", table_name="metraj_import_exclusions")
    op.drop_index("ix_metraj_import_exclusions_organization_id", table_name="metraj_import_exclusions")
    op.drop_table("metraj_import_exclusions")
