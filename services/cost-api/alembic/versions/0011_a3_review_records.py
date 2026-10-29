"""Add immutable saved technical reviews, separate from decisions and estimates."""
import sqlalchemy as sa

from alembic import op

revision = "0011_a3_review_records"
down_revision = "0010_m521_safe_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("technical_review_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a3_record_request"))
    for field in ("organization_id", "project_id", "import_id"):
        op.create_index(f"ix_technical_review_records_{field}", "technical_review_records", [field])


def downgrade():
    op.drop_table("technical_review_records")
