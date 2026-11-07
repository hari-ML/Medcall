"""SQLAlchemy models for MedRecall (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    #: owner (Phase 2). NULL = legacy/orphan row from before accounts existed;
    #: orphan rows are invisible to every patient (isolation by construction).
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "patients.id",
            ondelete="CASCADE",
            name="fk_prescriptions_patient_id",  # named: SQLite batch DDL needs it
        ),
        nullable=True,
        index=True,
    )

    patient: Mapped["Patient | None"] = relationship(back_populates="prescriptions")

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


# ---------------------------------------------------------------------------
# Accounts (Phase 2)
# ---------------------------------------------------------------------------


class Patient(Base):
    """A patient account. Phone is the login identity (OTP-verified)."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    #: normalised E.164-ish form, e.g. "+919812345678"
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    #: preferred UI/instruction language
    preferred_lang: Mapped[str] = mapped_column(String(5), default="en", nullable=False)
    #: IANA timezone for reminder scheduling (Phase 3)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)

    caregiver_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    caregiver_phone: Mapped[str] = mapped_column(String(20), default="", nullable=False)

    prescriptions: Mapped[list["Prescription"]] = relationship(back_populates="patient")


class OtpCode(Base):
    """A one-time phone verification code (hash at rest, 10-minute expiry)."""

    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    phone: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    #: HMAC-SHA256(secret, phone:code) — the raw 6-digit code is never stored
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: failed verify attempts on this code
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RefreshToken(Base):
    """A rotating, revocable refresh token (JWT `jti` stored here).

    Replay detection: if an already-consumed jti is presented again, the whole
    session family for that patient is revoked (token theft response).
    """

    __tablename__ = "refresh_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )


class ConsentRecord(Base):
    """Explicit per-channel communication consent (WhatsApp/SMS/voice).

    Any reminder channel MUST re-check this before sending (Phase 3+):
    no consent row or granted=False means NO message.
    """

    __tablename__ = "consent_records"
    __table_args__ = (UniqueConstraint("patient_id", "channel", name="uq_consent_patient_channel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: "whatsapp" | "sms" | "voice"
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
