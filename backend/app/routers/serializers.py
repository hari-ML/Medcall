"""Shared serialization helpers for the prescription endpoints.

``_item_out`` is the single serializer for medicine items: every API response,
schedule build and reminder build reads items through it, so a field rename
here would surface everywhere at once (contract tests catch it).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..core.security import signed_image_url
from ..models import MedicineItem, Patient, Prescription
from ..schemas import ItemOut, PatientOut, PrescriptionOut


def _item_out(item: MedicineItem) -> ItemOut:
    return ItemOut(
        id=item.id,
        line_number=item.line_number,
        medicine=item.medicine_name or "",
        strength=item.strength or None,
        form=item.form or None,
        frequency=item.frequency or None,
        food_timing=item.food_timing or None,
        duration_days=item.duration_days,
        as_needed=bool(item.as_needed),
        slots=list(item.slots or []),
        status=item.status,
        reason=item.reason or "",
        source_text=item.source_text,
        confidence=item.ocr_confidence,
    )


def _item_dict(item: MedicineItem) -> dict[str, Any]:
    """Same data as _item_out, shaped for schedule/reminder builders."""
    return _item_out(item).model_dump()


def _prescription_out(prescription: Prescription) -> PrescriptionOut:
    # Signed, expiring URL (Phase 2): still starts with "/uploads/", so
    # existing startswith() assertions keep holding, and <img src> works.
    image_url = (
        signed_image_url(prescription) if prescription.image_filename else None
    )
    return PrescriptionOut(
        id=prescription.id,
        image_url=image_url,
        lang=prescription.lang,
        created_at=prescription.created_at,
        items=[_item_out(i) for i in prescription.items],
    )


def _get_prescription(db: Session, prescription_id: int) -> Prescription:
    prescription = db.get(Prescription, prescription_id)
    if prescription is None:
        raise HTTPException(status_code=404, detail="Prescription not found.")
    return prescription


def _get_owned_prescription(db: Session, prescription_id: int, patient: Patient) -> Prescription:
    """Ownership-aware lookup (Phase 2 isolation).

    Someone else's prescription (or a legacy orphan row with patient_id NULL)
    is indistinguishable from a missing one: always a plain 404, never a 403,
    so record existence does not leak across accounts.
    """
    prescription = _get_prescription(db, prescription_id)
    if prescription.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Prescription not found.")
    return prescription


def _patient_out(patient: Patient) -> PatientOut:
    return PatientOut(
        id=patient.id,
        phone=patient.phone,
        phone_verified=patient.phone_verified,
        full_name=patient.full_name,
        preferred_lang=patient.preferred_lang,
        timezone=patient.timezone,
        caregiver_name=patient.caregiver_name,
        caregiver_phone=patient.caregiver_phone,
        created_at=patient.created_at,
    )


def _get_item(prescription: Prescription, item_id: int) -> MedicineItem:
    item = next((i for i in prescription.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Medicine line not found.")
    return item


_FOOD_WORDS = {
    "before": "before food",
    "after": "after food",
    "with": "with food",
    "empty_stomach": "empty stomach",
}


def _compose_source_text(fields) -> str:
    """Build an editable line from the inline edit form."""
    if fields.source_text and fields.source_text.strip():
        return fields.source_text.strip()
    parts: list[str] = []
    if fields.form:
        parts.append(str(fields.form).strip().capitalize())
    if fields.medicine_name:
        parts.append(str(fields.medicine_name).strip())
    if fields.strength:
        parts.append(str(fields.strength).strip())
    if fields.frequency:
        parts.append(str(fields.frequency).strip())
    if fields.food_timing:
        parts.append(_FOOD_WORDS.get(str(fields.food_timing).strip(), str(fields.food_timing).strip()))
    if fields.duration_days is not None:
        parts.append(f"x {int(fields.duration_days)} days")
    return " ".join(p for p in parts if p)
