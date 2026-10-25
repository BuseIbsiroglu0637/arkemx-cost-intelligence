"""M1 initial product, tenant and licensed source models.

Revision ID: 0001_m1_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_m1_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_table("imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("stored_key", sa.String(500), nullable=False),
        sa.Column("sheet_name", sa.String(100), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_imports_project_id", "imports", ["project_id"])
    op.create_table("work_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("imports.id"), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("raw_description", sa.Text(), nullable=False),
        sa.Column("raw_quantity", sa.Text(), nullable=True),
        sa.Column("raw_unit", sa.String(50), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("normalized_unit", sa.String(30), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("import_id", "source_row", name="uq_import_row"))
    op.create_index("ix_work_items_import_id", "work_items", ["import_id"])
    op.create_table("catalog_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("institution", sa.String(200), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license_status", sa.String(20), nullable=False),
        sa.Column("license_evidence", sa.Text(), nullable=True),
        sa.Column("permission_scope", sa.Text(), nullable=True),
        sa.Column("verified_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("license_status IN ('pending','verified','rejected')", name="ck_license_status"))
    op.create_index("ix_catalog_sources_organization_id", "catalog_sources", ["organization_id"])
    op.create_table("catalog_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(40), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_catalog_versions_source_id", "catalog_versions", ["source_id"])
    op.create_table("catalog_positions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("catalog_versions.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.UniqueConstraint("version_id", "code", name="uq_catalog_code_version"))
    op.create_index("ix_catalog_positions_version_id", "catalog_positions", ["version_id"])


def downgrade():
    for table in ("catalog_positions", "catalog_versions", "catalog_sources", "work_items", "imports", "projects", "users", "organizations"):
        op.drop_table(table)
