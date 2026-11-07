"""Prescription endpoints: upload -> OCR, fetch, confirm/edit, schedule, PDF, reminders.

Moved verbatim out of ``main.py`` in Phase 1 (paths and payload shapes
unchanged). Two behavioural notes:

* OCR is CPU-bound: it runs via ``run_in_threadpool`` so one upload cannot
  stall the event loop for every other request.
* THE SAFETY RULE lives here: ``patch_item`` is the ONLY route from
  ``unclear`` -> scheduleable, it re-runs the gate on edits, and it can only
  ever assign ``confirmed`` / ``edited`` / ``unclear`` — never ``clear``
  (``scripts/safety_audit.mjs`` A6 greps this file for those exact lines).
"""

from __future__ import annotations

import hmac
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..core.config import UPLOAD_DIR
from ..core.deps import get_current_patient
from ..core.security import sign_image_url
from ..db import get_db
from ..models import Patient, Prescription
from ..ocr import OcrError, ocr_file
from ..parser import parse_line
from ..pdf import render_timetable_pdf
from ..schemas import ItemOut, PatchItemIn, PrescriptionOut, ReminderOut, ScheduleOut
from ..schedule import build_reminders, build_schedule
from ..seed import create_prescription_from_ocr
from ..uncertainty import STATUS_CLEAR, STATUS_CONFIRMED, STATUS_EDITED, STATUS_UNCLEAR, gate
from .serializers import (
    _compose_source_text,
    _get_item,
    _get_owned_prescription,
    _item_dict,
    _item_out,
    _prescription_out,
)

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def _ocr_and_create(
    path: Path,
    *,
    is_pdf: bool,
    db: Session,
    image_filename: str,
    original_filename: str,
    content_type: str,
    patient_id: int | None = None,
):
    """OCR + persist in a worker thread (keeps the event loop responsive)."""
    ocr_lines = ocr_file(path, is_pdf=is_pdf)
    return create_prescription_from_ocr(
        db,
        ocr_lines,
        image_filename=image_filename,
        original_filename=original_filename,
        content_type=content_type,
        patient_id=patient_id,
    )


@router.post("/api/prescriptions", response_model=PrescriptionOut, status_code=201)
async def upload_prescription(
    file: UploadFile = File(..., description="JPG / PNG / PDF photo of a prescription (max 10 MB)"),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> PrescriptionOut:
    content_type = (file.content_type or "").lower()
    suffix = Path(file.filename or "").suffix.lower()

    if content_type not in ALLOWED_CONTENT_TYPES or suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a JPG, PNG or PDF of the prescription (max 10 MB).",
        )

    # stream with a hard size cap
    contents = bytearray()
    while chunk := await file.read(1024 * 1024):
        contents.extend(chunk)
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="File is too large. The maximum upload size is 10 MB.",
            )
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    filename = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / filename
    path.write_bytes(bytes(contents))

    try:
        prescription = await run_in_threadpool(
            _ocr_and_create,
            path,
            is_pdf=suffix == ".pdf",
            db=db,
            image_filename=filename,
            original_filename=file.filename or filename,
            content_type=content_type,
            patient_id=patient.id,
        )
    except OcrError:
        path.unlink(missing_ok=True)
        raise  # -> JSON 422 via exception handler
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _prescription_out(prescription)


@router.get("/api/prescriptions", response_model=list[PrescriptionOut])
def list_prescriptions(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> list[PrescriptionOut]:
    """The caller's own prescriptions, newest first (Phase 2)."""
    rows = (
        db.query(Prescription)
        .filter(Prescription.patient_id == patient.id)
        .order_by(Prescription.created_at.desc(), Prescription.id.desc())
        .all()
    )
    return [_prescription_out(row) for row in rows]


@router.get("/api/prescriptions/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(
    prescription_id: int,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> PrescriptionOut:
    return _prescription_out(_get_owned_prescription(db, prescription_id, patient))


# ---------------------------------------------------------------------------
# Confirm / edit an item (the ONLY way unclear -> scheduleable)
# ---------------------------------------------------------------------------


@router.patch("/api/prescriptions/{prescription_id}/items/{item_id}", response_model=ItemOut)
def patch_item(
    prescription_id: int,
    item_id: int,
    body: PatchItemIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> ItemOut:
    prescription = _get_owned_prescription(db, prescription_id, patient)
    item = _get_item(prescription, item_id)

    if body.action == "confirm":
        # A human vouched for this line -> it may enter the schedule.
        item.status = STATUS_CONFIRMED
        item.reason = ""
        db.commit()
        db.refresh(item)
        return _item_out(item)

    # action == "edit": rebuild the line, RE-VALIDATE with the gate.
    if body.fields is None:
        raise HTTPException(status_code=400, detail="Edit requires a 'fields' object.")

    source_text = _compose_source_text(body.fields)
    if not source_text:
        raise HTTPException(status_code=400, detail="Edit produced an empty line.")

    # Human-typed text: OCR confidence no longer applies.
    item.source_text = source_text
    item.ocr_confidence = 100.0
    parsed = parse_line(source_text, ocr_confidence=100.0)
    result = gate(parsed)

    item.medicine_name = parsed.medicine_name.value or ""
    item.strength = parsed.strength.value or ""
    item.form = parsed.form.value or ""
    item.frequency = parsed.frequency.value or ""
    item.food_timing = parsed.food_timing.value or ""
    item.duration_days = int(parsed.duration_days.value) if parsed.duration_days.value else None
    item.as_needed = parsed.as_needed
    item.slots = list(parsed.slots)

    if result.status == STATUS_CLEAR:
        # User-supplied AND passed the gate -> "edited" (never auto-"clear").
        item.status = STATUS_EDITED
        item.reason = ""
    else:
        # Still fails the gate: stays unclear with fresh reasons.
        item.status = STATUS_UNCLEAR
        item.reason = result.reason

    db.commit()
    db.refresh(item)
    return _item_out(item)


# ---------------------------------------------------------------------------
# Schedule / PDF / reminders
# ---------------------------------------------------------------------------


@router.post("/api/prescriptions/{prescription_id}/schedule", response_model=ScheduleOut)
def post_schedule(
    prescription_id: int,
    lang: str = Query("en", pattern="^(en|ta|hi)$"),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    prescription = _get_owned_prescription(db, prescription_id, patient)
    items = [_item_dict(i) for i in prescription.items]
    return build_schedule(items, lang=lang)  # type: ignore[return-value]


@router.get("/api/prescriptions/{prescription_id}/timetable.pdf")
def get_timetable_pdf(
    prescription_id: int,
    lang: str = Query("en", pattern="^(en|ta|hi)$"),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> Response:
    prescription = _get_owned_prescription(db, prescription_id, patient)
    items = [_item_dict(i) for i in prescription.items]
    try:
        pdf_bytes = render_timetable_pdf(items, lang=lang)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Could not build the PDF: {exc}") from exc
    filename = f"medrecall_timetable_{prescription_id}_{lang}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/api/prescriptions/{prescription_id}/reminders", response_model=list[ReminderOut])
def get_reminders(
    prescription_id: int,
    lang: str = Query("en", pattern="^(en|ta|hi)$"),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> list[ReminderOut]:
    prescription = _get_owned_prescription(db, prescription_id, patient)
    items = [_item_dict(i) for i in prescription.items]
    return build_reminders(items, lang=lang)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Uploaded images — signed, expiring URLs (Phase 2: public mount removed)
# ---------------------------------------------------------------------------

#: stored file names are uuid-hex + extension; anything else is rejected
_IMAGE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


@router.get("/uploads/{filename}")
def get_prescription_image(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve an uploaded image through its signed, expiring URL.

    Access requires ``?exp=<unix-ts>&sig=HMAC(secret, "<prescription_id>:<filename>:<exp>")``
    (see ``core.security.sign_image_url``), valid for 15 minutes. No Bearer
    token is needed so plain ``<img src>`` embedding keeps working.
    """
    if not _IMAGE_FILENAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="Image not found.")
    path = UPLOAD_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    prescription = (
        db.query(Prescription).filter(Prescription.image_filename == filename).first()
    )
    if prescription is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    try:
        exp = int(request.query_params.get("exp", ""))
    except ValueError:
        raise HTTPException(status_code=403, detail="Image link is invalid.") from None
    sig = request.query_params.get("sig", "")
    expected = sign_image_url(prescription.id, filename, exp)
    if exp < int(time.time()) or not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=403, detail="Image link is expired or invalid.")
    return FileResponse(path)
