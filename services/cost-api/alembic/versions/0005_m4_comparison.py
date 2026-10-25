"""M4 technical comparisons frozen per candidate.

Revision ID: 0005_m4_comparison
Revises: 0004_m3_catalog
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_m4_comparison"
down_revision = "0004_m3_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "technical_comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36),
                  sa.ForeignKey("match_candidates.id"), unique=True, nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('blocked','review','compatible')",
                           name="ck_technical_comparison_status"),
    )
    op.create_index("ix_technical_comparisons_candidate_id",
                    "technical_comparisons", ["candidate_id"])


def downgrade():
    op.drop_index("ix_technical_comparisons_candidate_id",
                  table_name="technical_comparisons")
    op.drop_table("technical_comparisons")
