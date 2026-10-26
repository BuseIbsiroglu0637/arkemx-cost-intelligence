"""M1 schema with organization ownership and traceable imports/catalog rights."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, DateTime, ForeignKey, Integer, Numeric, Boolean, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def ident():
    return str(uuid4())


def now_utc():
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="admin", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class ImportBatch(Base):
    __tablename__ = "imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(100), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (UniqueConstraint("import_id", "source_row", name="uq_import_row"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), index=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    raw_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    normalized_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class CatalogSource(Base):
    __tablename__ = "catalog_sources"
    __table_args__ = (CheckConstraint("license_status IN ('pending','verified','rejected')", name="ck_license_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    license_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    license_evidence: Mapped[str | None] = mapped_column(Text)
    permission_scope: Mapped[str | None] = mapped_column(Text)
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CatalogVersion(Base):
    __tablename__ = "catalog_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CatalogPosition(Base):
    __tablename__ = "catalog_positions"
    __table_args__ = (UniqueConstraint("version_id", "code", name="uq_catalog_code_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    version_id: Mapped[str] = mapped_column(ForeignKey("catalog_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3), default="TRY", nullable=False)


class MatchRun(Base):
    __tablename__ = "match_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("catalog_versions.id"), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("match_runs.id"), nullable=True)
    changed_item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(80), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (UniqueConstraint("run_id", "work_item_id", "rank", name="uq_match_rank"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    run_id: Mapped[str] = mapped_column(ForeignKey("match_runs.id"), index=True, nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True, nullable=False)
    position_id: Mapped[str] = mapped_column(ForeignKey("catalog_positions.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    similarity: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    approvable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class MatchDecision(Base):
    __tablename__ = "match_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("match_candidates.id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class WorkItemRevision(Base):
    """Append-only expert corrections; original uploaded WorkItem is immutable."""
    __tablename__ = "work_item_revisions"
    __table_args__ = (UniqueConstraint("work_item_id", "revision", name="uq_item_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    corrected_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class MatchRunItemSnapshot(Base):
    """Frozen effective item at match time; later corrections cannot rewrite history."""
    __tablename__ = "match_run_item_snapshots"
    __table_args__ = (UniqueConstraint("run_id", "work_item_id", name="uq_run_item_snapshot"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    run_id: Mapped[str] = mapped_column(ForeignKey("match_runs.id"), index=True, nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True, nullable=False)
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("work_item_revisions.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CatalogImport(Base):
    """Staged local catalog; tenant admin cannot make it matchable."""
    __tablename__ = "catalog_imports"
    __table_args__ = (
        UniqueConstraint("organization_id", "sha256", "source_id", "year", "period",
                         name="uq_catalog_import_file_period"),
        CheckConstraint("status IN ('pending','approved','rejected')",
                        name="ck_catalog_import_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("catalog_versions.id"), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String(40), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approval_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_scope: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CatalogReviewEvent(Base):
    """Append-only privileged, local-operator rights review ledger."""
    __tablename__ = "catalog_review_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    catalog_import_id: Mapped[str] = mapped_column(ForeignKey("catalog_imports.id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class TechnicalComparison(Base):
    """Immutable M4 candidate evidence generated at match-run creation."""
    __tablename__ = "technical_comparisons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("match_candidates.id"), unique=True, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class TechnicalEvidence(Base):
    """M4.1 per-candidate immutable source-backed evidence snapshot."""
    __tablename__ = "technical_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("match_candidates.id"), unique=True, index=True, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class BulkJob(Base):
    """M4.3 durable, bounded, single-worker batch job. One row per request."""
    __tablename__ = "bulk_jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_bulk_project_request"),
        CheckConstraint("status IN ('queued','running','completed','failed','blocked')",
                        name="ck_bulk_job_status"),
        CheckConstraint("processed_rows >= 0 AND candidate_count >= 0", name="ck_bulk_job_counts"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("catalog_versions.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("match_runs.id"), unique=True, nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CostEstimate(Base):
    """Immutable, user-priced draft; NOT an approved quote or public rate schedule."""
    __tablename__ = "cost_estimates"
    __table_args__ = (
        UniqueConstraint("project_id", "request_key", name="uq_cost_estimate_request"),
        CheckConstraint("currency = 'TRY'", name="ck_cost_currency"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("match_runs.id"), index=True, nullable=False)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("catalog_versions.id"), nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="TRY", nullable=False)
    total: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CostEstimateLine(Base):
    """Frozen metraj/poz, explicit manual price and rounded line amount."""
    __tablename__ = "cost_estimate_lines"
    __table_args__ = (
        UniqueConstraint("estimate_id", "candidate_id", name="uq_cost_line_candidate"),
        UniqueConstraint("estimate_id", "work_item_id", name="uq_cost_line_item"),
        CheckConstraint("quantity > 0 AND unit_price > 0 AND amount >= 0", name="ck_cost_positive"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    estimate_id: Mapped[str] = mapped_column(ForeignKey("cost_estimates.id"), index=True, nullable=False)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("match_candidates.id"), nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), nullable=False)
    position_id: Mapped[str] = mapped_column(ForeignKey("catalog_positions.id"), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    position_code: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)
    price_source: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

class MetrajRevisionEvent(Base):
    """Append-only lineage for explicit M5.2 revised Excel imports."""
    __tablename__ = "metraj_revision_events"
    __table_args__ = (UniqueConstraint("new_import_id", name="uq_m52_new_import"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    baseline_import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    new_import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    baseline_estimate_id: Mapped[str | None] = mapped_column(ForeignKey("cost_estimates.id"), nullable=True)
    old_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    new_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
