"""Pydantic v2 schemas (API request/response models) for MedRecall."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

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
