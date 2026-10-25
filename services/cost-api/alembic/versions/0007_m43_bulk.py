"""M4.3 persistent local bulk job state.

Revision ID: 0007_m43_bulk
Revises: 0006_m41_evidence
"""
from alembic import op
import sqlalchemy as sa
revision="0007_m43_bulk"
down_revision="0006_m41_evidence"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table(
        "bulk_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("catalog_versions.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("match_runs.id"), nullable=False, unique=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("processed_rows", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(300), nullable=True),
        sa.Column("lease_owner", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','blocked')", name="ck_bulk_job_status"),
        sa.CheckConstraint("processed_rows >= 0 AND candidate_count >= 0", name="ck_bulk_job_counts"),
        sa.UniqueConstraint("project_id","idempotency_key",name="uq_bulk_project_request"),
    )
    op.create_index("ix_bulk_org", "bulk_jobs", ["organization_id"])
    op.create_index("ix_bulk_project", "bulk_jobs", ["project_id"])
    op.create_index("ix_bulk_created", "bulk_jobs", ["created_at"])
    op.create_index("ix_bulk_status", "bulk_jobs", ["status"])
    # Race-safe single active job for a project (SQLite and PostgreSQL).
    op.create_index("uq_bulk_active_project", "bulk_jobs", ["project_id"], unique=True,
                    sqlite_where=sa.text("status IN (\u0027queued\u0027,\u0027running\u0027)"),
                    postgresql_where=sa.text("status IN (\u0027queued\u0027,\u0027running\u0027)"))

def downgrade():
    op.drop_index("uq_bulk_active_project", table_name="bulk_jobs")
    op.drop_index("ix_bulk_status", table_name="bulk_jobs")
    op.drop_index("ix_bulk_created", table_name="bulk_jobs")
    op.drop_index("ix_bulk_project", table_name="bulk_jobs")
    op.drop_index("ix_bulk_org", table_name="bulk_jobs")
    op.drop_table("bulk_jobs")
