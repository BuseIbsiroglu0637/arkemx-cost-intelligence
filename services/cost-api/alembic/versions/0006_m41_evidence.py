"""M4.1 immutable source-anchored technical evidence.

Revision ID: 0006_m41_evidence
Revises: 0005_m4_comparison
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_m41_evidence"
down_revision = "0005_m4_comparison"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "technical_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36),
                  sa.ForeignKey("match_candidates.id"), nullable=False, unique=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('blocked','review','compatible')",
                           name="ck_technical_evidence_status"),
    )
    op.create_index("ix_technical_evidence_candidate_id",
                    "technical_evidence", ["candidate_id"])


def downgrade():
    op.drop_index("ix_technical_evidence_candidate_id", table_name="technical_evidence")
    op.drop_table("technical_evidence")
