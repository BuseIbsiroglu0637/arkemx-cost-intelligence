"""Append-only preparation decisions; no engineering approval or cost grant."""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import ident, now_utc


class EngineerHandoffDecision(Base):
    __tablename__ = "a327_handoff_decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_id", "request_key",
                         name="uq_a327_decision_request"),
        UniqueConstraint("work_item_id", "previous_key",
                         name="uq_a327_decision_chain"),
        CheckConstraint(
            "action IN ('request_information', 'reject_candidate', "
            "'submit_for_engineering_review')",
            name="ck_a327_decision_action",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), index=True, nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True, nullable=False)
    candidate_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_at_decision: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    previous_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False,
    )
