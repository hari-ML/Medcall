"""SQLAlchemy models for MedRecall (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: stored file name under /uploads ("" for a demo prescription)
    image_filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    lang: Mapped[str] = mapped_column(String(5), default="en", nullable=False)

    items: Mapped[list["MedicineItem"]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
        order_by="MedicineItem.line_number",
    )


class MedicineItem(Base):
    __tablename__ = "medicine_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 1-based position in the original document (shown as "Line 3" in the UI)
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: OCR confidence 0-100 (100 when the user typed the line manually)
    ocr_confidence: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)

    medicine_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    strength: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    form: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    frequency: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    food_timing: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_needed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: fixed daily slots derived from the frequency code (JSON list)
    slots: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # --- safety gate output -------------------------------------------------
    #: clear | unclear | confirmed | edited   (never auto-promoted)
    status: Mapped[str] = mapped_column(String(16), default="unclear", nullable=False)
    #: human-readable reason while status == "unclear"
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    prescription: Mapped["Prescription"] = relationship(back_populates="items")
