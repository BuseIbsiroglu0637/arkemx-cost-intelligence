"""M3 catalog staging and explicit operator rights gate.

Revision ID: 0004_m3_catalog
Revises: 0003_m21_revisions
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_m3_catalog"
down_revision = "0003_m21_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("catalog_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("catalog_versions.id"), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(40), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(160)),
        sa.Column("approval_evidence", sa.Text()),
        sa.Column("approval_scope", sa.String(80)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending','approved','rejected')", name="ck_catalog_import_status"),
        sa.UniqueConstraint("organization_id","sha256","source_id","year","period",
                            name="uq_catalog_import_file_period"),
    )
    op.create_index("ix_catalog_imports_organization_id","catalog_imports",["organization_id"])
    op.create_table("catalog_review_events",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("catalog_import_id",sa.String(36),sa.ForeignKey("catalog_imports.id"),nullable=False),
        sa.Column("action",sa.String(20),nullable=False),
        sa.Column("reviewer",sa.String(160),nullable=False),
        sa.Column("scope",sa.String(80),nullable=False),
        sa.Column("evidence_sha256",sa.String(64),nullable=False),
        sa.Column("catalog_sha256",sa.String(64),nullable=False),
        sa.Column("reason",sa.Text(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
    )
    op.create_index("ix_catalog_review_events_catalog_import_id",
                    "catalog_review_events",["catalog_import_id"])


def downgrade():
    op.drop_index("ix_catalog_review_events_catalog_import_id",
                  table_name="catalog_review_events")
    op.drop_table("catalog_review_events")
    op.drop_index("ix_catalog_imports_organization_id", table_name="catalog_imports")
    op.drop_table("catalog_imports")
