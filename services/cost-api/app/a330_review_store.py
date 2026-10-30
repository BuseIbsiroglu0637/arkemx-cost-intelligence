"""A3.30 immutable proposal revisions and qualified-engineer signoffs.

No source PDFs are changed. An engineer record must be independently provisioned;
the ordinary organization admin account is not a qualified engineer.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import ident, now_utc


class ProposedAnalysisRevision(Base):
    __tablename__ = "a330_analysis_revisions"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_a330_revision_version"),
        UniqueConstraint("organization_id", "project_id", "request_key",
                         name="uq_a330_revision_request"),
        CheckConstraint("version > 0", name="ck_a330_revision_version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_code: Mapped[str] = mapped_column(String(80), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_amount: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class VerifiedEngineeringReviewer(Base):
    """Provisioned *outside* the user-facing API after identity/qualification checks."""
    __tablename__ = "a330_verified_engineers"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    verified_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    verification_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EngineeringSignoff(Base):
    __tablename__ = "a330_engineering_signoffs"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_id", "request_key",
                         name="uq_a330_signoff_request"),
        CheckConstraint("action IN ('approve','reject')", name="ck_a330_signoff_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True, nullable=False)
    analysis_revision_id: Mapped[str] = mapped_column(ForeignKey("a330_analysis_revisions.id"), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    signed_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
