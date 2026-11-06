"""OCR plumbing tests: Tesseract/Poppler discovery and photo orientation.

These do not call the real OCR engine (the API tests already exercise a real
Tesseract upload); they pin the environment fixes that make uploads work on a
stock Windows install:

* WinGet installs Poppler in a versioned package folder and does not add it to
  PATH — ``find_poppler()`` must discover it (or honour ``POPPLER_PATH``).
* phone photos store rotation in EXIF — the decoder must apply it, otherwise
  portrait prescriptions are OCR'd sideways.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from app import ocr


def _pdftoppm_name() -> str:
    return "pdftoppm.exe" if os.name == "nt" else "pdftoppm"


def test_find_poppler_honours_explicit_env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "poppler" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / _pdftoppm_name()).write_bytes(b"")
    monkeypatch.setenv("POPPLER_PATH", str(bin_dir))
    assert ocr.find_poppler() == str(bin_dir)


def test_find_poppler_returns_a_real_directory_on_this_machine():
    found = ocr.find_poppler()
    if found is None:
        pytest.skip("Poppler is not installed on this machine")
    assert (Path(found) / _pdftoppm_name()).is_file()


def test_ocr_image_file_applies_exif_orientation(tmp_path, monkeypatch):
    path = tmp_path / "portrait.jpg"
    image = Image.new("RGB", (120, 60), "white")
    exif = image.getexif()
    exif[274] = 6  # Orientation: rotate 90° — displayed size becomes 60 x 120
    image.save(path, format="JPEG", exif=exif)

    captured: dict[str, tuple[int, int]] = {}

    monkeypatch.setattr(ocr, "configure_tesseract", lambda: {"eng"})

    def fake_ocr_pil(img, lang):  # noqa: ARG001
        captured["size"] = img.size
        return []

    monkeypatch.setattr(ocr, "ocr_pil_image", fake_ocr_pil)

    assert ocr.ocr_image_file(path, lang="eng") == []
    assert captured["size"] == (60, 120)


def test_pdf_ocr_passes_detected_poppler_to_pdf2image(tmp_path, monkeypatch):
    pdf2image = pytest.importorskip("pdf2image")
    pdf = tmp_path / "rx.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake test file\n")

    monkeypatch.setattr(ocr, "configure_tesseract", lambda: {"eng"})
    monkeypatch.setattr(ocr, "find_poppler", lambda: r"C:\poppler\bin")

    captured: dict[str, object] = {}

    def fake_convert(path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return []

    monkeypatch.setattr(pdf2image, "convert_from_path", fake_convert)

    assert ocr.ocr_pdf_file(pdf, lang="eng") == []
    assert captured["path"] == str(pdf)
    assert captured["poppler_path"] == r"C:\poppler\bin"
    assert captured["dpi"] == 300
