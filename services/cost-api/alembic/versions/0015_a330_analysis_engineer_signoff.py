"""A3.30: proposed analysis revisions and verified-human engineering signoff."""
import sqlalchemy as sa
from alembic import op

revision = "0015_a330_analysis_engineer_signoff"
down_revision = "0014_a327_handoff_decisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "a330_analysis_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidate_code", sa.String(80), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("analysis_pdf_sha256", sa.String(64), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("proposed_amount", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("work_item_id", "version", name="uq_a330_revision_version"),
        sa.UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a330_revision_request"),
        sa.CheckConstraint("version > 0", name="ck_a330_revision_version"),
    )
    for name in ("organization_id", "project_id", "work_item_id"):
        op.create_index(f"ix_a330_analysis_revisions_{name}", "a330_analysis_revisions", [name])

    op.create_table(
        "a330_verified_engineers",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("verified_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verification_reference", sa.String(255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "a330_engineering_signoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("analysis_revision_id", sa.String(36), sa.ForeignKey("a330_analysis_revisions.id"), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("signed_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a330_signoff_request"),
        sa.CheckConstraint("action IN ('approve','reject')", name="ck_a330_signoff_action"),
    )
    for name in ("organization_id", "project_id", "work_item_id"):
        op.create_index(f"ix_a330_engineering_signoffs_{name}", "a330_engineering_signoffs", [name])


def downgrade():
    op.drop_table("a330_engineering_signoffs")
    op.drop_table("a330_verified_engineers")
    op.drop_table("a330_analysis_revisions")
