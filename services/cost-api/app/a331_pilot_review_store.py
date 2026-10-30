"""Audit-only pilot review decisions; NEVER qualified engineering signoffs or M5 cost clearance."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import ident, now_utc


class PilotTechnicalReviewEvent(Base):
    __tablename__ = "a331_pilot_technical_review_events"
    __table_args__ = (
        UniqueConstraint("work_item_id", "sequence", name="uq_a331_pilot_item_sequence"),
        UniqueConstraint("organization_id", "project_id", "request_key", name="uq_a331_pilot_request"),
        CheckConstraint("sequence > 0", name="ck_a331_pilot_sequence"),
        CheckConstraint("action IN ('accept','reopen')", name="ck_a331_pilot_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ident)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"), nullable=False)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_revision_id: Mapped[str] = mapped_column(
        ForeignKey("a330_analysis_revisions.id"), nullable=False,
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
