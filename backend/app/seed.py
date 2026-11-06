"""Demo/seed data for MedRecall.

Provides the DEMO prescription text (the same fixture shown in sample_data/)
and a shared builder that turns OCR lines into prescription + item rows,
running the full safety pipeline: extract -> parse -> gate.

The upload endpoint in main.py reuses :func:`create_prescription_from_ocr`,
so demo data and real uploads are processed identically.

CLI:
    python -m app.seed --demo          # insert the demo prescription
    python -m app.seed --text ../sample_data/full_prescription.txt
    python -m app.seed --image ../sample_data/rx.png   # runs real OCR
    python -m app.seed --list          # list what is in the database
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from .extract import extract_medicine_lines
from .models import MedicineItem, Prescription
from .ocr import OcrLine, ocr_file
from .parser import parse_line
from .uncertainty import gate

#: Prefilled demo prescription: three clear lines + one "Dose unreadable"
#: line (so the review/uncertainty UI can be demonstrated without OCR).
DEMO_TEXT = """City General Hospital
Dr. Meera Raghavan
Date: 15/11/2026
Patient: Ramanathan S. (68)

Rx
Tab Paracetamol 500 mg 1-0-1 after food x 5 days
Cap Amoxicillin 250 mg 1-1-1 x 5 days
Tab Cetirizine ?? mg 0-0-1
Syp Cough Syrup 5 ml TDS SOS
Advice: Complete the full course
"""


def create_prescription_from_ocr(
    db: Session,
    ocr_lines: list[OcrLine],
    *,
    image_filename: str = "",
    original_filename: str = "",
    content_type: str = "",
    lang: str = "en",
) -> Prescription:
    """Run extract -> parse -> gate on OCR lines and persist a prescription.

    Raises ValueError if no medicine lines are found (caller decides the
    HTTP error). Commits the session.
    """
    candidates = extract_medicine_lines(ocr_lines)
    if not candidates:
        raise ValueError(
            "No medicine lines could be detected in this file. "
            "Please upload a clearer photo, or try the demo prescription."
        )

    prescription = Prescription(
        image_filename=image_filename,
        original_filename=original_filename,
        content_type=content_type,
        lang=lang,
    )
    db.add(prescription)
    db.flush()  # assign prescription.id

    for candidate in candidates:
        parsed = parse_line(candidate.text, ocr_confidence=candidate.confidence)
        result = gate(parsed)
        item = MedicineItem(
            prescription_id=prescription.id,
            line_number=candidate.line_number,
            source_text=candidate.text,
            ocr_confidence=candidate.confidence,
            medicine_name=parsed.medicine_name.value or "",
            strength=parsed.strength.value or "",
            form=parsed.form.value or "",
            frequency=parsed.frequency.value or "",
            food_timing=parsed.food_timing.value or "",
            duration_days=int(parsed.duration_days.value) if parsed.duration_days.value else None,
            as_needed=parsed.as_needed,
            slots=list(parsed.slots),
            status=result.status,
            reason=result.reason,
        )
        db.add(item)

    db.commit()
    db.refresh(prescription)
    return prescription


def text_to_ocr_lines(text: str, confidence: float = 95.0) -> list[OcrLine]:
    """Turn plain prescription text (a fixture) into OCR-like lines."""
    return [
        OcrLine(text=line, confidence=confidence)
        for line in text.splitlines()
        if line.strip()
    ]


def create_demo_prescription(db: Session) -> Prescription:
    """Insert the prefilled demo prescription (no OCR required)."""
    return create_prescription_from_ocr(
        db,
        text_to_ocr_lines(DEMO_TEXT),
        image_filename="",
        original_filename="demo_prescription.png",
        content_type="image/png",
    )


def _cli() -> None:  # pragma: no cover - manual tool
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Seed MedRecall with sample data")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="insert the built-in demo prescription")
    group.add_argument("--text", metavar="FILE", help="seed from a .txt prescription fixture")
    group.add_argument("--image", metavar="FILE", help="seed from an image/PDF via real OCR")
    group.add_argument("--list", action="store_true", help="list stored prescriptions")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.list:
            rows = db.query(Prescription).order_by(Prescription.id).all()
            if not rows:
                print("No prescriptions yet.")
            for rx in rows:
                print(f"#{rx.id}  {rx.created_at}  items={len(rx.items)}  "
                      f"statuses={[i.status for i in rx.items]}")
            return
        if args.demo:
            rx = create_demo_prescription(db)
            print(f"Demo prescription #{rx.id} created with {len(rx.items)} items.")
        elif args.text:
            text = Path(args.text).read_text(encoding="utf-8")
            rx = create_prescription_from_ocr(
                db, text_to_ocr_lines(text),
                original_filename=Path(args.text).name, content_type="text/plain",
            )
            print(f"Prescription #{rx.id} from {args.text}: {len(rx.items)} items.")
        elif args.image:
            lines = ocr_file(args.image)
            rx = create_prescription_from_ocr(
                db, lines,
                image_filename=Path(args.image).name,
                original_filename=Path(args.image).name,
                content_type="image",
            )
            print(f"Prescription #{rx.id} from {args.image}: {len(rx.items)} items.")
        for item in rx.items:
            print(f"  [{item.status:>9}] {item.source_text}"
                  + (f"  -> {item.reason}" if item.reason else ""))
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    _cli()
