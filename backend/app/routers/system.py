"""Demo + health endpoints (moved from ``main.py`` in Phase 1, unchanged)."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from .. import __version__
from ..core.config import UPLOAD_DIR
from ..db import get_db
from ..ocr import OcrError, configure_tesseract, find_poppler, find_tesseract
from ..schemas import HealthOut, PrescriptionOut
from ..seed import DEMO_TEXT, create_prescription_from_ocr, text_to_ocr_lines
from .serializers import _prescription_out

router = APIRouter()


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
# Demo mode (no OCR)
# ---------------------------------------------------------------------------


@router.post("/api/demo", response_model=PrescriptionOut, status_code=201)
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


@router.get("/api/health", response_model=HealthOut)
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
