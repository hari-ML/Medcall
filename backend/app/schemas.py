"""Pydantic v2 schemas (API request/response models) for MedRecall."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

LangCode = Literal["en", "ta", "hi"]


# ---------------------------------------------------------------------------
# Items / prescriptions
# ---------------------------------------------------------------------------


class ItemOut(BaseModel):
    id: int
    line_number: int
    medicine: str
    strength: Optional[str] = None
    form: Optional[str] = None
    frequency: Optional[str] = None
    food_timing: Optional[str] = None
    duration_days: Optional[int] = None
    as_needed: bool = False
    slots: list[str] = Field(default_factory=list)
    status: str
    reason: str = ""
    source_text: str
    confidence: float


class PrescriptionOut(BaseModel):
    id: int
    image_url: Optional[str] = None
    lang: str = "en"
    created_at: datetime
    items: list[ItemOut]


# ---------------------------------------------------------------------------
# Confirm / edit
# ---------------------------------------------------------------------------


class EditFields(BaseModel):
    """User-edited values. Either full fields or an explicit source line."""

    medicine_name: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    frequency: Optional[str] = None
    food_timing: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, ge=0, le=365)
    source_text: Optional[str] = None


class PatchItemIn(BaseModel):
    action: Literal["confirm", "edit"]
    fields: Optional[EditFields] = None


# ---------------------------------------------------------------------------
# Schedule / reminders
# ---------------------------------------------------------------------------


class SlotEntryOut(BaseModel):
    id: Optional[int] = None
    medicine: str
    instruction: str
    time: Optional[str] = None
    slot: Optional[str] = None
    status: str


class AsNeededEntryOut(BaseModel):
    id: Optional[int] = None
    medicine: str
    instruction: str
    status: str


class ExcludedEntryOut(BaseModel):
    id: Optional[int] = None
    medicine: str
    status: str
    reason: str
    source_text: str
    line_number: Optional[int] = None


class ScheduleOut(BaseModel):
    lang: str
    date: str
    title: str
    disclaimer: str
    as_needed_heading: str
    excluded_heading: str
    empty_slot_note: str
    slots: dict[str, list[SlotEntryOut]]
    as_needed: list[AsNeededEntryOut]
    excluded: list[ExcludedEntryOut]
    slot_times: dict[str, str]


class ReminderOut(BaseModel):
    time: str
    medicine: str
    instruction: str
    slot: str
    id: Optional[int] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthOut(BaseModel):
    status: str
    version: str
    tesseract: Optional[str] = None
    languages: list[str] = Field(default_factory=list)
    poppler: Optional[str] = None
    note: str = ""


# ---------------------------------------------------------------------------
# Auth (Phase 2): phone OTP login, tokens, profiles, consent
# ---------------------------------------------------------------------------


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=7, max_length=20)


class OtpRequestOut(BaseModel):
    message: str
    expires_in: int
    #: ONLY present in non-production environments (no SMS provider yet).
    dev_code: Optional[str] = None


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    code: str = Field(pattern=r"^[0-9]{6}$")
    full_name: Optional[str] = Field(default=None, max_length=255)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PatientOut(BaseModel):
    id: int
    phone: str
    phone_verified: bool
    full_name: str
    preferred_lang: str
    timezone: str
    caregiver_name: str = ""
    caregiver_phone: str = ""
    created_at: datetime


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    patient: PatientOut


class PatientUpdateIn(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    preferred_lang: Optional[LangCode] = None
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    caregiver_name: Optional[str] = Field(default=None, max_length=255)
    caregiver_phone: Optional[str] = Field(default=None, max_length=20)


ChannelCode = Literal["whatsapp", "sms", "voice"]


class ConsentIn(BaseModel):
    channel: ChannelCode
    granted: bool


class ConsentOut(BaseModel):
    channel: str
    granted: bool
    #: None when no consent row exists yet (channel never touched)
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Reminder engine (Phase 3)
# ---------------------------------------------------------------------------


class EnrolledItemOut(BaseModel):
    item_id: int
    medicine: str
    slot: str
    #: local HH:MM in the patient's timezone
    time_of_day: str


class SkippedItemOut(BaseModel):
    item_id: int
    medicine: str
    reason: str


class EnrollmentOut(BaseModel):
    scheduled_doses: int
    items: list[EnrolledItemOut]
    skipped: list[SkippedItemOut]


class OccurrenceOut(BaseModel):
    id: int
    item_id: int
    medicine: str
    slot: str
    #: naive UTC ISO timestamp
    scheduled_at: datetime
    #: HH:MM in the patient's IANA timezone
    local_time: str
    status: str
    channel: str
    body: str
    error: str
    attempts: int = 0
    #: naive UTC; set only while a transient failure waits for its retry
    next_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


class ReminderRunOut(BaseModel):
    generated: int
    sent: int
    blocked: int
    failed: int
    missed: int
    cancelled: int


# ---------------------------------------------------------------------------
# AI care agent (Phase 5)
# ---------------------------------------------------------------------------


class AgentChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    #: answer language; omitted -> the patient's preferred language
    lang: Optional[LangCode] = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("message must not be blank")
        return text


class AgentSourceOut(BaseModel):
    prescription_id: int
    item_id: Optional[int] = None
    medicine: str
    status: str


class AgentChatOut(BaseModel):
    reply: str
    lang: str
    intent: str
    grounded: bool
    escalate: bool
    safety_blocked: bool
    disclaimer: str
    sources: list[AgentSourceOut] = Field(default_factory=list)


class AgentSuggestionsOut(BaseModel):
    lang: str
    suggestions: list[str]


# ---------------------------------------------------------------------------
# Admin dashboard (Phase 6) — read-only, separate credential
# ---------------------------------------------------------------------------


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class AdminLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str = "admin"


class AdminStatsOut(BaseModel):
    patients: int
    prescriptions: int
    #: item status -> count across all patients
    items_by_status: dict[str, int]
    active_reminder_schedules: int
    #: occurrence status -> count (pending/sent/blocked/failed/missed/cancelled)
    occurrences_by_status: dict[str, int]
    #: consented channel -> patient count
    consent_by_channel: dict[str, int]


class AdminPatientOut(BaseModel):
    id: int
    phone: str
    full_name: str
    preferred_lang: str
    timezone: str
    created_at: datetime
    prescriptions: int
    items: int
    active_schedules: int


class AdminPatientsOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AdminPatientOut]


class AdminPatientDetailOut(BaseModel):
    patient: PatientOut
    prescriptions: list[PrescriptionOut]
    consent: list[ConsentOut]
    active_schedules: int


class AdminOccurrenceOut(BaseModel):
    id: int
    patient_id: int
    patient_phone: str
    medicine: str
    slot: str
    #: local HH:MM in the patient's timezone
    time_of_day: str
    #: naive UTC ISO timestamp
    scheduled_at: datetime
    status: str
    channel: str
    attempts: int
    sent_at: Optional[datetime] = None


class AdminRemindersOut(BaseModel):
    limit: int
    items: list[AdminOccurrenceOut]
