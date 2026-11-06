"""MedRecall FastAPI application.

Endpoints
---------
POST   /api/prescriptions                          upload image/PDF -> OCR -> items
GET    /api/prescriptions/{id}                     fetch for the review screen
PATCH  /api/prescriptions/{id}/items/{item_id}     confirm / edit an unclear item
POST   /api/prescriptions/{id}/schedule?lang=...   timetable (clear/confirmed/edited only)
GET    /api/prescriptions/{id}/timetable.pdf       printable PDF
GET    /api/prescriptions/{id}/reminders?lang=...  reminder feed
GET    /api/health                                 OCR availability check
POST   /api/demo                                   prefilled prescription (no OCR)

THE SAFETY RULE: unclear items are never translated, scheduled, printed or
used for reminders — see uncertainty.SCHEDULEABLE_STATUSES.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from . import DISCLAIMER, __version__
from .db import get_db, init_db
from .models import MedicineItem, Prescription
from .ocr import OcrError, configure_tesseract, find_poppler, find_tesseract, ocr_file
from .parser import parse_line
from .pdf import render_timetable_pdf
from .schemas import (
    HealthOut,
    ItemOut,
    PatchItemIn,
    PrescriptionOut,
    ReminderOut,
    ScheduleOut,
)
from .schedule import build_reminders, build_schedule
from .seed import DEMO_TEXT, create_prescription_from_ocr, text_to_ocr_lines
from .translate import TranslationError, UnsupportedLanguageError
from .uncertainty import STATUS_CLEAR, STATUS_CONFIRMED, STATUS_EDITED, STATUS_UNCLEAR, gate

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MedRecall API",
    description="Making medicine instructions simple, safe and understandable. " + DISCLAIMER,
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

init_db()  # create tables on import (idempotent)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


# ---------------------------------------------------------------------------
# Clean JSON errors
# ---------------------------------------------------------------------------


@app.exception_handler(OcrError)
async def _ocr_error_handler(request, exc: OcrError):  # noqa: ARG001
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(TranslationError)
async def _translation_error_handler(request, exc: TranslationError):  # noqa: ARG001
    status = 400 if isinstance(exc, UnsupportedLanguageError) else 500
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


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
    image_url = f"/uploads/{prescription.image_filename}" if prescription.image_filename else None
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


def _render_demo_image(text: str) -> str:
    """Render the demo prescription text to a PNG so the review screen has a
    real image to show. Returns the stored file name."""
    filename = f"demo_{uuid.uuid4().hex[:12]}.png"
    width, line_height = 1050, 36
    lines = text.splitlines()
    img = Image.new("RGB", (width, 60 + line_height * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    font_path = "C:/Windows/Fonts/arial.ttf" if os.name == "nt" else "DejaVuSans.ttf"
    try:
        font = ImageFont.truetype(font_path, 26)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle([10, 10, width - 10, 50 + line_height * len(lines)],
                   outline="#0F766E", width=2)
    y = 30
    for line in lines:
        draw.text((30, y), line, fill="#0F172A", font=font)
        y += line_height
    img.save(UPLOAD_DIR / filename, "PNG")
    return filename


# ---------------------------------------------------------------------------
# Upload: image/PDF -> OCR -> items
# ---------------------------------------------------------------------------


@app.post("/api/prescriptions", response_model=PrescriptionOut, status_code=201)
async def upload_prescription(
    file: UploadFile = File(..., description="JPG / PNG / PDF photo of a prescription (max 10 MB)"),
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
        ocr_lines = ocr_file(path, is_pdf=suffix == ".pdf")
        prescription = create_prescription_from_ocr(
            db,
            ocr_lines,
            image_filename=filename,
            original_filename=file.filename or filename,
            content_type=content_type,
        )
    except OcrError:
        path.unlink(missing_ok=True)
        raise  # -> JSON 422 via exception handler
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _prescription_out(prescription)


@app.get("/api/prescriptions/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(prescription_id: int, db: Session = Depends(get_db)) -> PrescriptionOut:
    return _prescription_out(_get_prescription(db, prescription_id))


# ---------------------------------------------------------------------------
# Confirm / edit an item (the ONLY way unclear -> scheduleable)
# ---------------------------------------------------------------------------


@app.patch("/api/prescriptions/{prescription_id}/items/{item_id}", response_model=ItemOut)
def patch_item(
    prescription_id: int,
    item_id: int,
    body: PatchItemIn,
    db: Session = Depends(get_db),
) -> ItemOut:
    prescription = _get_prescription(db, prescription_id)
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


@app.post("/api/prescriptions/{prescription_id}/schedule", response_model=ScheduleOut)
def post_schedule(
    prescription_id: int,
    lang: str = Query("en", pattern="^(en|ta|hi)$"),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    prescription = _get_prescription(db, prescription_id)
    items = [_item_dict(i) for i in prescription.items]
    return build_schedule(items, lang=lang)  # type: ignore[return-value]


@app.get("/api/prescriptions/{prescription_id}/timetable.pdf")
def get_timetable_pdf(
    prescription_id: int,
    lang: str = Query("en", pattern="^(en|ta|hi)$"),
    db: Session = Depends(get_db),
) -> Response:
    prescription = _get_prescription(db, prescription_id)
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


@app.get("/api/prescriptions/{prescription_id}/reminders", response_model=list[ReminderOut])
def get_reminders(
    prescription_id: int,
    lang: str = Query("en", pattern="^(en|ta|hi)$"),
    db: Session = Depends(get_db),
) -> list[ReminderOut]:
    prescription = _get_prescription(db, prescription_id)
    items = [_item_dict(i) for i in prescription.items]
    return build_reminders(items, lang=lang)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Demo mode (no OCR)
# ---------------------------------------------------------------------------


@app.post("/api/demo", response_model=PrescriptionOut, status_code=201)
def create_demo(db: Session = Depends(get_db)) -> PrescriptionOut:
    """Prefilled prescription: three clear lines + one 'Dose unreadable' line."""
    image_filename = _render_demo_image(DEMO_TEXT)
    prescription = create_prescription_from_ocr(
        db,
        text_to_ocr_lines(DEMO_TEXT),
        image_filename=image_filename,
        original_filename="demo_prescription.png",
        content_type="image/png",
    )
    return _prescription_out(prescription)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthOut)
def health() -> HealthOut:
    try:
        langs = sorted(configure_tesseract())
        poppler = find_poppler()
        ocr_note = (
            "OCR ready (eng + tam + hin available)"
            if {"tam", "hin"} <= set(langs)
            else "OCR ready (English only — Tamil/Hindi language packs not found)"
        )
        pdf_note = (
            "PDF uploads ready"
            if poppler
            else "PDF uploads disabled (Poppler/pdftoppm not found) — image uploads still work"
        )
        return HealthOut(
            status="ok",
            version=__version__,
            tesseract=find_tesseract(),
            languages=langs,
            poppler=poppler,
            note=f"{ocr_note}; {pdf_note}",
        )
    except OcrError as exc:
        return HealthOut(status="degraded", version=__version__, note=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return HealthOut(status="degraded", version=__version__, note=f"Unexpected OCR error: {exc}")
