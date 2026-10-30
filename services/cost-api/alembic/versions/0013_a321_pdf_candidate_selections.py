"""Save candidate picks by source revision without creating engineering approvals."""
import sqlalchemy as sa
from alembic import op

revision = "0013_a321_candidate_selections"
down_revision = "0012_a3_review_assessments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pdf_candidate_selections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("work_item_revisions.id"), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=False),
        sa.Column("position_code", sa.String(80), nullable=False),
        sa.Column("selected_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("work_item_id", name="uq_pdf_candidate_work_item"),
    )
    for field in ("organization_id", "project_id", "import_id", "work_item_id"):
        op.create_index(f"ix_pdf_candidate_selections_{field}", "pdf_candidate_selections", [field])


def downgrade():
    op.drop_table("pdf_candidate_selections")
