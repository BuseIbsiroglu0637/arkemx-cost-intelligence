"""Append assessment history without changing saved evidence or M4 decisions."""
import sqlalchemy as sa

from alembic import op

revision = "0012_a3_review_assessments"
down_revision = "0011_a3_review_records"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("technical_review_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("record_id", sa.String(36), sa.ForeignKey("technical_review_records.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("candidate_code", sa.String(64), nullable=True),
        sa.Column("revision_id", sa.String(36), nullable=True),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("previous_key", sa.String(36), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a3_assessment_request"),
        sa.UniqueConstraint("record_id", "work_item_id", "previous_key", name="uq_a3_assessment_chain"),
        sa.CheckConstraint("action IN ('reject_candidate', 'request_information')", name="ck_a3_assessment_action"))
    for field in ("organization_id", "project_id", "record_id", "work_item_id"):
        op.create_index(f"ix_technical_review_assessments_{field}", "technical_review_assessments", [field])


def downgrade():
    op.drop_table("technical_review_assessments")
