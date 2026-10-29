"""Append-only review assessments, separate from engineering approval."""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import ident, now_utc


class TechnicalReviewAssessment(Base):
    __tablename__ = "technical_review_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a3_assessment_request"),
        UniqueConstraint("record_id", "work_item_id", "previous_key", name="uq_a3_assessment_chain"),
        CheckConstraint("action IN ('reject_candidate', 'request_information')", name="ck_a3_assessment_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("technical_review_records.id"), index=True)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    candidate_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    previous_key: Mapped[str] = mapped_column(String(36))
    request_key: Mapped[str] = mapped_column(String(36))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
