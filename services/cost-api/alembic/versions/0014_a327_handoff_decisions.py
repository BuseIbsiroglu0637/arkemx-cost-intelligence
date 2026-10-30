"""A3.27.2 append-only human readiness notes, never approval."""
import sqlalchemy as sa
from alembic import op

revision = "0014_a327_handoff_decisions"
down_revision = "0013_a321_candidate_selections"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "a327_handoff_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("candidate_code", sa.String(80), nullable=True),
        sa.Column("revision_id", sa.String(36), nullable=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=True),
        sa.Column("status_at_decision", sa.String(40), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("previous_key", sa.String(36), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a327_decision_request"),
        sa.UniqueConstraint("work_item_id", "previous_key", name="uq_a327_decision_chain"),
        sa.CheckConstraint(
            "action IN ('request_information', 'reject_candidate', 'submit_for_engineering_review')",
            name="ck_a327_decision_action",
        ),
    )
    for field in ("organization_id", "project_id", "import_id", "work_item_id"):
        op.create_index(f"ix_a327_handoff_decisions_{field}", "a327_handoff_decisions", [field])


def downgrade():
    op.drop_table("a327_handoff_decisions")
