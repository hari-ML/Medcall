"""OCR for MedRecall: image/PDF -> list of text lines with confidence.

Pipeline::

    file -> (PDF: pdf2image -> pages) -> PIL image
         -> OpenCV preprocessing (grayscale, denoise, adaptive threshold)
         -> Tesseract ("eng+tam+hin", graceful fallback to "eng")
         -> list[OcrLine(text, confidence 0-100)]

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
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageOps


class OcrError(Exception):
    """Raised when OCR cannot run at all (missing Tesseract, unreadable file...)."""


@dataclass
class OcrLine:
    """One line of extracted text with its confidence (0-100)."""

    text: str
    confidence: float


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


def preprocess_image(img: Image.Image) -> Image.Image:
    """Grayscale -> denoise -> adaptive threshold (OpenCV)."""
    import cv2  # imported lazily so the module loads even if cv2 is broken

    gray = np.array(img.convert("L"))
    gray = cv2.medianBlur(gray, 3)
    thresholded = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
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
