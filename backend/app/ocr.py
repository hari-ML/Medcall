"""OCR for MedRecall: image/PDF -> text lines + optional structured rows.

Pipeline::

    file -> (PDF: pdf2image -> pages) -> PIL image
         -> OpenCV preprocessing (grayscale, shadow removal, denoise,
            adaptive Gaussian threshold)
         -> Tesseract ("eng+tam+hin", graceful fallback to "eng")
         -> list[OcrLine(text, confidence 0-100)]

When ``GEMINI_API_KEY`` is configured the upload path first asks Gemini
Vision (``gemini-2.5-flash``) for strict JSON: the raw transcription plus one
row per medicine (name/dosage/frequency/times/meal_instruction/duration/
confidence/uncertainty_reason). Those rows are synthesized back into
prescription lines in ``parser.py`` and pushed through the same
extract -> parse -> gate pipeline as Tesseract output — the model never
assigns a status. Without a key, or if the model call fails, the preprocessed
Tesseract pipeline runs (uploads never depend on the key being set).

Safety: this module only extracts text. It never interprets, guesses, or
"cleans up" meaning. All interpretation happens in parser.py and all safety
decisions in uncertainty.py.

Tesseract resolution on this machine (Windows):
    1. ``tesseract`` on PATH
    2. Common install locations (C:\\Program Files\\Tesseract-OCR\\...)
Language data (tessdata):
    * Default system tessdata first.
    * If tam/hin packs live in the per-user folder
      (%LOCALAPPDATA%\\Tesseract-OCR\\tessdata) we point TESSDATA_PREFIX there.
    * If Indic packs are unavailable we fall back to "eng" and record it,
      so uploads still work (Indic text on the photo may then be imperfect —
      the uncertainty gate protects against that with per-line confidence).
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pytesseract
from PIL import Image, ImageOps

from .core.config import get_settings

logger = logging.getLogger("medrecall.ocr")


class OcrError(Exception):
    """Raised when OCR cannot run at all (missing Tesseract, unreadable file...)."""


@dataclass
class OcrLine:
    """One line of extracted text with its confidence (0-100)."""

    text: str
    confidence: float


@dataclass
class StructuredMedicine:
    """One validated medicine row from Gemini Vision's strict JSON.

    This is a *transcription* record, not a decision: every field mirrors what
    is printed on the prescription, and anything the model could not read is
    left empty. ``confidence`` is the model's own 0-1 self-report and only
    ever lowers the line's OCR confidence — the uncertainty gate still decides
    clear/unclear (a non-empty ``uncertainty_reason`` caps it below 70).
    """

    name: str
    dosage: str = ""
    form: str = ""
    frequency: str = ""
    times: list[str] = field(default_factory=list)
    meal_instruction: str = ""
    duration_days: int | None = None
    confidence: float = 0.0
    uncertainty_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dosage": self.dosage,
            "form": self.form,
            "frequency": self.frequency,
            "times": list(self.times),
            "meal_instruction": self.meal_instruction,
            "duration_days": self.duration_days,
            "confidence": self.confidence,
            "uncertainty_reason": self.uncertainty_reason,
        }


@dataclass
class OcrBundle:
    """Everything the OCR layer extracted from one upload.

    ``structured`` is empty on the Tesseract path; ``engine`` and ``notes``
    record what actually ran so callers/logs never pretend Gemini succeeded.
    """

    lines: list[OcrLine]
    structured: list[StructuredMedicine] = field(default_factory=list)
    engine: str = "tesseract"
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tesseract discovery + language setup
# ---------------------------------------------------------------------------

_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
]


def find_tesseract() -> str | None:
    """Locate the tesseract executable (PATH first, then known locations)."""
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _TESSERACT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def find_poppler() -> str | None:
    """Locate the Poppler ``bin`` directory containing ``pdftoppm``.

    pdf2image does not search common Windows install locations itself. WinGet
    installs Poppler under a versioned package folder and does not add it to
    PATH, so a plain ``convert_from_path()`` fails even though Poppler is
    installed. Returns the directory to pass as ``poppler_path`` (or ``None``).
    """
    env = os.environ.get("POPPLER_PATH")
    if env:
        base = Path(env)
        for candidate in (base, base / "bin", base / "Library" / "bin"):
            if _has_pdftoppm(candidate):
                return str(candidate)

    found = shutil.which("pdftoppm")
    if found:
        return str(Path(found).parent)

    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
            if packages.is_dir():
                for candidate in packages.glob("oschwartz10612.Poppler_*/poppler-*/Library/bin"):
                    if _has_pdftoppm(candidate):
                        return str(candidate)
        for pattern in (
            r"C:\Program Files\poppler*\Library\bin",
            r"C:\Program Files\poppler*\bin",
            r"C:\Program Files (x86)\poppler*\Library\bin",
            r"C:\ProgramData\chocolatey\bin",
        ):
            for candidate in glob.glob(pattern):
                if _has_pdftoppm(Path(candidate)):
                    return candidate
    return None


def _has_pdftoppm(directory: Path) -> bool:
    return (directory / "pdftoppm.exe").is_file() or (directory / "pdftoppm").is_file()


def _per_user_tessdata_dir() -> Path | None:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Tesseract-OCR" / "tessdata"
    return None


def _raw_available_langs() -> set[str]:
    """Languages visible to tesseract under the current TESSDATA_PREFIX."""
    result = pytesseract.get_languages(config="")
    return set(result) if result else set()


def configure_tesseract() -> set[str]:
    """Point pytesseract at the tesseract binary and the best tessdata dir.

    Returns the set of available language codes after setup.
    """
    exe = find_tesseract()
    if not exe:
        raise OcrError(
            "Tesseract OCR is not installed. Install it from "
            "https://github.com/UB-Mannheim/tesseract/wiki and restart the server."
        )
    pytesseract.pytesseract.tesseract_cmd = exe

    langs = _raw_available_langs()
    missing = {"tam", "hin"} - langs
    if missing:
        per_user = _per_user_tessdata_dir()
        if per_user and per_user.is_dir():
            have = {p.stem.lower() for p in per_user.glob("*.traineddata")}
            if "eng" in have and (missing <= have):
                os.environ["TESSDATA_PREFIX"] = str(per_user)
                langs = _raw_available_langs()
    return langs


def choose_lang(available: set[str]) -> str:
    """Pick the best language string: eng+tam+hin > eng."""
    if {"eng", "tam", "hin"} <= available:
        return "eng+tam+hin"
    if "eng" in available:
        return "eng"
    raise OcrError("No usable Tesseract language data found (need at least 'eng').")


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------


def remove_shadows(gray: np.ndarray) -> np.ndarray:
    """Flatten uneven lighting (phone-photo shadows) from a grayscale image.

    OpenCV recipe: dilate to erase thin strokes, median-blur the result into a
    smooth background estimate, subtract it from the page, then stretch the
    remainder back to full contrast. Text stays dark, shadows become white.
    """
    import cv2  # imported lazily so the module loads even if cv2 is broken

    if gray.ndim != 2:
        raise ValueError("remove_shadows expects a 2-D grayscale array")
    kernel = np.ones((7, 7), np.uint8)
    dilated = cv2.dilate(gray, kernel)
    background = cv2.medianBlur(dilated, 21)
    difference = 255 - cv2.absdiff(gray, background)
    normalized = cv2.normalize(
        difference, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX
    )
    return normalized.astype(np.uint8)


def preprocess_image(img: Image.Image) -> Image.Image:
    """Grayscale -> shadow removal -> denoise -> adaptive Gaussian threshold."""
    import cv2  # imported lazily so the module loads even if cv2 is broken

    gray = np.array(img.convert("L"))
    gray = remove_shadows(gray)
    gray = cv2.medianBlur(gray, 3)
    thresholded = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    return Image.fromarray(thresholded, "L")


# ---------------------------------------------------------------------------
# Line extraction from Tesseract output
# ---------------------------------------------------------------------------


def _lines_from_data(data: dict) -> list[OcrLine]:
    """Group image_to_data word entries back into reading-order lines."""
    grouped: dict[tuple[int, int, int], list[str]] = {}
    confs: dict[tuple[int, int, int], list[int]] = {}
    order: list[tuple[int, int, int]] = []

    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = int(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < 0:  # not a word detection
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        if key not in grouped:
            grouped[key] = []
            confs[key] = []
            order.append(key)
        grouped[key].append(text)
        confs[key].append(conf)

    lines: list[OcrLine] = []
    for key in order:
        words = grouped[key]
        line_text = " ".join(words)
        if not line_text.strip():
            continue
        confidence = sum(confs[key]) / len(confs[key])
        lines.append(OcrLine(text=line_text, confidence=round(confidence, 1)))
    return lines


def ocr_pil_image(img: Image.Image, lang: str) -> list[OcrLine]:
    """OCR one in-memory image. Tries the preprocessed version first,
    falls back to plain grayscale if the threshold destroyed the text."""
    try:
        processed = preprocess_image(img)
    except Exception:
        processed = img.convert("L")

    try:
        data = pytesseract.image_to_data(
            processed, lang=lang, output_type=pytesseract.Output.DICT
        )
        lines = _lines_from_data(data)
        if sum(len(l.text) for l in lines) < 12:
            # Thresholding likely hurt (e.g. photo of a screen) — retry raw gray.
            gray = img.convert("L")
            data = pytesseract.image_to_data(gray, lang=lang, output_type=pytesseract.Output.DICT)
            alt = _lines_from_data(data)
            if sum(len(l.text) for l in alt) > sum(len(l.text) for l in lines):
                lines = alt
        return lines
    except pytesseract.TesseractError as exc:
        raise OcrError(f"Tesseract failed on this image: {exc}") from exc


# ---------------------------------------------------------------------------
# Gemini Vision (Part 3): strict-JSON structured transcription
# ---------------------------------------------------------------------------

#: The model is a transcriber, not a prescriber. Every rule below exists to
#: stop it from filling gaps: empty strings/nulls are the honest answer and
#: the uncertainty gate flags the row for a human.
_GEMINI_PROMPT = """You are a prescription transcription engine.
Read the attached prescription and return ONLY JSON with this exact shape:
{
  "raw_text": "full transcription, one line per line of the page",
  "medicines": [
    {
      "name": "medicine name exactly as printed",
      "dosage": "strength/amount as printed, e.g. 500 mg or 5 ml (empty if unreadable)",
      "form": "tablet | capsule | syrup | injection | drops | cream | inhaler | sachet | other (lower-case, empty if unknown)",
      "frequency": "printed sig or expansion, e.g. 1-0-1, twice daily, TDS, SOS (empty if unreadable)",
      "times": ["explicit clock times only, 24-hour HH:MM; [] when none are printed"],
      "meal_instruction": "before food | after food | with food | empty stomach (empty if not printed)",
      "duration_days": 5,
      "confidence": 0.0,
      "uncertainty_reason": "short reason when any field is unclear, else empty string"
    }
  ]
}
Rules:
- Transcribe only what is visible. Never guess or invent a medicine, dose,
  frequency, time, meal instruction or duration. Use "" / null / [] instead.
- Include every medicine line; omit headers, doctor names, dates and advice.
- "confidence" is your own 0-1 certainty for the whole row.
- Return JSON only, with no markdown fences and no commentary."""


def _gemini_configured() -> bool:
    return bool(get_settings().gemini_api_key.strip())


def _clean_text(value: object, limit: int = 300) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _clean_confidence(value: object) -> float:
    """Clamp the model's self-report to 0-1; missing means zero (unclear)."""
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if confidence > 1.0:  # some models answer on a 0-100 scale
        confidence /= 100.0
    return round(min(max(confidence, 0.0), 1.0), 3)


def _clean_duration(value: object) -> int | None:
    try:
        days = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return days if 0 < days <= 365 else None


def _strip_json_fences(text: str) -> str:
    payload = text.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", payload)
        payload = re.sub(r"\s*```$", "", payload)
    return payload.strip()


def parse_gemini_response(text: str) -> tuple[str, list[StructuredMedicine]]:
    """Validate Gemini's strict JSON into transcription records.

    Raises ValueError when the payload is not the agreed shape. Rows without
    a name are dropped (there is nothing a human could review); every other
    field is coerced defensively and left empty when the model omitted it.
    """
    payload = _strip_json_fences(text)
    if not payload:
        raise ValueError("Gemini returned an empty response")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Gemini response is not a JSON object")

    raw_text = str(data.get("raw_text") or "")
    rows = data.get("medicines") or []
    if not isinstance(rows, list):
        raise ValueError("Gemini response 'medicines' is not a list")

    medicines: list[StructuredMedicine] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"), limit=120)
        if not name:
            continue
        raw_times = row.get("times") or []
        if isinstance(raw_times, str):
            raw_times = [raw_times]
        if not isinstance(raw_times, list):
            raw_times = []
        times = [t for t in (_clean_text(v, limit=20) for v in raw_times) if t]
        medicines.append(
            StructuredMedicine(
                name=name,
                dosage=_clean_text(row.get("dosage"), limit=60),
                form=_clean_text(row.get("form"), limit=40).lower(),
                frequency=_clean_text(row.get("frequency"), limit=80),
                times=times,
                meal_instruction=_clean_text(row.get("meal_instruction"), limit=60),
                duration_days=_clean_duration(row.get("duration_days")),
                confidence=_clean_confidence(row.get("confidence")),
                uncertainty_reason=_clean_text(
                    row.get("uncertainty_reason"), limit=200
                ),
            )
        )
    return raw_text, medicines


def _gemini_input(path: Path, is_pdf: bool) -> tuple[bytes, str]:
    """Bytes + MIME type for Gemini. Images are normalised to upright PNG."""
    if is_pdf:
        return path.read_bytes(), "application/pdf"
    try:
        img = Image.open(path)
        img.load()
        img = ImageOps.exif_transpose(img)
        buffer = BytesIO()
        img.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"
    except Exception as exc:
        raise OcrError(f"Could not read this image file: {exc}") from exc


def gemini_extract(
    data: bytes, mime_type: str
) -> tuple[str, list[StructuredMedicine]] | None:
    """Ask Gemini Vision for structured JSON. ``None`` = not configured.

    Any SDK/network/parse failure is logged and returned as ``None`` so the
    caller can fall back to Tesseract — an OCR outage must never take uploads
    down, and a fallback is honest (the gate still vets every line).
    """
    settings = get_settings()
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning(
            "GEMINI_API_KEY is set but google-genai is not installed; "
            "falling back to Tesseract. Install backend/requirements.txt."
        )
        return None

    try:
        client = genai.Client(
            api_key=api_key,
            http_options={"timeout": int(settings.gemini_timeout_seconds * 1000)},
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime_type),
                _GEMINI_PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        text = getattr(response, "text", "") or ""
        return parse_gemini_response(text)
    except Exception as exc:  # network, quota, safety block, bad JSON…
        logger.warning(
            "Gemini Vision extraction failed (%s); falling back to Tesseract.",
            str(exc)[:300],
        )
        return None


def ocr_bundle(path: str | Path, is_pdf: bool = False) -> OcrBundle:
    """Extract text + structured rows from one upload.

    Gemini runs first when configured; structured rows win only when at least
    one medicine was transcribed. Otherwise (no key, SDK error, empty result)
    the preprocessed Tesseract pipeline runs. The bundle always says which
    engine produced it.
    """
    path = Path(path)
    if not path.exists():
        raise OcrError(f"File not found: {path.name}")
    is_pdf = is_pdf or path.suffix.lower() == ".pdf"

    notes: list[str] = []
    if _gemini_configured():
        data, mime_type = _gemini_input(path, is_pdf)
        extracted = gemini_extract(data, mime_type)
        if extracted is not None:
            raw_text, medicines = extracted
            if medicines:
                lines = [
                    OcrLine(text=line.strip(), confidence=90.0)
                    for line in raw_text.splitlines()
                    if line.strip()
                ]
                return OcrBundle(
                    lines=lines,
                    structured=medicines,
                    engine="gemini",
                    notes=notes,
                )
            notes.append("gemini returned no medicines; used tesseract")
        else:
            notes.append("gemini unavailable; used tesseract")

    lines = ocr_file(path, is_pdf=is_pdf)
    return OcrBundle(lines=lines, structured=[], engine="tesseract", notes=notes)


# ---------------------------------------------------------------------------
# File entry points
# ---------------------------------------------------------------------------

PDF_RENDER_ERROR = (
    "Could not render this PDF. PDF uploads require Poppler (pdftoppm). "
    "On Windows run:  winget install oschwartz10612.Poppler   — then restart "
    "the server. If Poppler is already installed, set POPPLER_PATH to its bin "
    "folder. Or upload a photo of the prescription instead."
)


def ocr_image_file(path: str | Path, lang: str | None = None) -> list[OcrLine]:
    """OCR a JPG/PNG file from disk."""
    langs = configure_tesseract()
    lang = lang or choose_lang(langs)
    try:
        img = Image.open(path)
        img.load()
        # Phone photos carry orientation in EXIF; without this, portrait
        # prescriptions are OCR'd sideways and come back as garbage.
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise OcrError(f"Could not read this image file: {exc}") from exc
    return ocr_pil_image(img, lang)


def ocr_pdf_file(path: str | Path, lang: str | None = None) -> list[OcrLine]:
    """OCR every page of a PDF (via pdf2image + Poppler)."""
    try:
        from pdf2image import convert_from_path
    except ImportError as exc:  # pragma: no cover
        raise OcrError("pdf2image is not installed.") from exc

    langs = configure_tesseract()
    lang = lang or choose_lang(langs)
    poppler_path = find_poppler()
    try:
        pages = convert_from_path(
            str(path), dpi=300, poppler_path=poppler_path
        )
    except Exception as exc:
        raise OcrError(PDF_RENDER_ERROR) from exc

    lines: list[OcrLine] = []
    for page in pages:
        lines.extend(ocr_pil_image(page, lang))
    return lines


def ocr_file(path: str | Path, is_pdf: bool = False) -> list[OcrLine]:
    """Dispatch to the right backend based on the file kind."""
    path = Path(path)
    if not path.exists():
        raise OcrError(f"File not found: {path.name}")
    if is_pdf or path.suffix.lower() == ".pdf":
        return ocr_pdf_file(path)
    return ocr_image_file(path)


if __name__ == "__main__":  # manual debugging: python -m app.ocr photo.jpg
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m app.ocr <image-or-pdf> [is_pdf]")
        raise SystemExit(1)
    target = sys.argv[1]
    as_pdf = len(sys.argv) > 2 and sys.argv[2].lower() in ("1", "true", "yes")
    for line in ocr_file(target, is_pdf=as_pdf):
        print(f"[{line.confidence:5.1f}] {line.text}")
