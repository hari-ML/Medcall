"""Printable PDF timetable for MedRecall (ReportLab).

Renders: title + date, disclaimer box, the four slot sections, an as-needed
section, an amber "Needs confirmation" warning box for excluded items, and
the disclaimer on every page footer.

Fonts: looks for NotoSansTamil-Regular.ttf / NotoSansDevanagari-Regular.ttf
in backend/fonts/. If an Indic font is missing the PDF is still produced:
it falls back to English text with an explanatory note — never a crash.
"""

from __future__ import annotations

import io
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .schedule import SLOT_ORDER, build_schedule
from .translate import get_translator

TEAL = colors.HexColor("#0F766E")
TEAL_LIGHT = colors.HexColor("#F0FDFA")
AMBER_BG = colors.HexColor("#FEF3C7")
AMBER_BORDER = colors.HexColor("#F59E0B")
AMBER_TEXT = colors.HexColor("#92400E")
GRAY = colors.HexColor("#64748B")

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
FONT_FILES = {
    "ta": "NotoSansTamil-Regular.ttf",
    "hi": "NotoSansDevanagari-Regular.ttf",
}

_registered: dict[str, str] = {}


def _ensure_fonts() -> None:
    """Register the Indic TTFs if present; silently keep going if not."""
    for lang, filename in FONT_FILES.items():
        if lang in _registered:
            continue
        path = FONTS_DIR / filename
        if not path.is_file():
            continue
        font_name = f"NotoLang-{lang}"
        try:
            pdfmetrics.registerFont(TTFont(font_name, str(path)))
            # map bold/italic lookups to the regular face so <b> never breaks
            pdfmetrics.registerFontFamily(font_name, normal=font_name, bold=font_name,
                                          italic=font_name, boldItalic=font_name)
            _registered[lang] = font_name
        except Exception:
            # corrupt/unsupported font file: fall back gracefully
            continue


def font_available(lang: str) -> bool:
    _ensure_fonts()
    if lang == "en":
        return True
    return lang in _registered


def _font_name(lang: str) -> str:
    _ensure_fonts()
    if lang == "en":
        return "Helvetica"
    return _registered.get(lang, "Helvetica")


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName=font_name, fontSize=19, leading=25,
                                textColor=TEAL, spaceAfter=2),
        "sub": ParagraphStyle("sub", fontName=font_name, fontSize=9.5, leading=13,
                              textColor=GRAY, spaceAfter=8),
        "section": ParagraphStyle("section", fontName=font_name, fontSize=13.5, leading=18,
                                  textColor=TEAL, spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("body", fontName=font_name, fontSize=10.5, leading=15),
        "body_bold": ParagraphStyle("body_bold", fontName=font_name, fontSize=10.5, leading=15,
                                    textColor=colors.HexColor("#0F172A")),
        "small": ParagraphStyle("small", fontName=font_name, fontSize=9, leading=13,
                                textColor=GRAY),
        "warn_head": ParagraphStyle("warn_head", fontName=font_name, fontSize=11.5, leading=15,
                                    textColor=AMBER_TEXT, spaceAfter=3),
        "warn_item": ParagraphStyle("warn_item", fontName=font_name, fontSize=9.8, leading=13.5,
                                    textColor=AMBER_TEXT, leftIndent=8),
        "note": ParagraphStyle("note", fontName=font_name, fontSize=9, leading=12.5,
                               textColor=AMBER_TEXT),
    }


def _entry_table(rows: list[tuple[str, str, str]], styles: dict[str, ParagraphStyle],
                 with_time: bool) -> Table:
    data = []
    for row in rows:
        if with_time:
            time_text, medicine, instruction = row
            data.append([
                Paragraph(time_text, styles["body_bold"]),
                Paragraph(medicine, styles["body_bold"]),
                Paragraph(instruction, styles["body"]),
            ])
        else:
            medicine, instruction = row
            data.append([
                Paragraph(medicine, styles["body_bold"]),
                Paragraph(instruction, styles["body"]),
            ])
    if with_time:
        col_widths = [52, 130, 333]
        header = [Paragraph("<b>Time</b>", styles["small"]),
                  Paragraph("<b>Medicine</b>", styles["small"]),
                  Paragraph("<b>How to take</b>", styles["small"])]
    else:
        col_widths = [150, 365]
        header = [Paragraph("<b>Medicine</b>", styles["small"]),
                  Paragraph("<b>How to take</b>", styles["small"])]
    table = Table([header] + data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL_LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    return table


def render_timetable_pdf(
    items: Iterable[Mapping[str, Any]],
    lang: str = "en",
) -> bytes:
    """Render the timetable for ``items`` in ``lang`` and return PDF bytes.

    Unclear items are excluded by build_schedule() and shown only in the
    amber warning box (never as schedule rows).
    """
    _ensure_fonts()
    render_lang = lang
    fallback_note: str | None = None
    if lang not in ("en",) and not font_available(lang):
        # Graceful degradation: no TTF for this language -> English + note.
        render_lang = "en"
        fallback_note = (
            f"Note: the {lang.upper()} font is missing from backend/fonts/ — this "
            "timetable was rendered in English. See fonts/README.md to add it."
        )

    schedule = build_schedule(list(items), lang=render_lang)
    translator = get_translator(render_lang)
    font_name = _font_name(render_lang)
    styles = _styles(font_name)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=20 * mm,
        title="MedRecall — Daily Medicine Timetable",
        author="MedRecall",
    )

    disclaimer = schedule["disclaimer"]

    def _footer(canvas, doc_):  # noqa: N803 (reportlab signature)
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(GRAY)
        canvas.drawString(16 * mm, 11 * mm, disclaimer)
        canvas.setFillColor(TEAL)
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(0.8)
        canvas.line(16 * mm, 15 * mm, A4[0] - 16 * mm, 15 * mm)
        canvas.restoreState()

    story = []

    # ------------------------------------------------ header + disclaimer box
    story.append(Paragraph(schedule["title"], styles["title"]))
    generated = datetime.now().strftime("%d %b %Y, %H:%M")
    story.append(Paragraph(
        f"{schedule['date']} &nbsp;·&nbsp; generated {generated} &nbsp;·&nbsp; MedRecall",
        styles["sub"],
    ))
    disclaimer_box = Table(
        [[Paragraph(f"<b>{disclaimer}</b>", styles["body"])]],
        colWidths=[515],
    )
    disclaimer_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TEAL_LIGHT),
        ("BOX", (0, 0), (-1, -1), 1, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(disclaimer_box)
    if fallback_note:
        story.append(Spacer(1, 6))
        story.append(Paragraph(fallback_note, styles["note"]))

    # ----------------------------------------------------------- four slots
    for slot in SLOT_ORDER:
        entries = schedule["slots"].get(slot, [])
        heading = translator.slot_name(slot)
        slot_time = schedule["slot_times"].get(slot, "")
        block: list[Any] = [Paragraph(f"{heading} &nbsp;·&nbsp; {slot_time}", styles["section"])]
        if entries:
            rows = [
                (e["time"], e["medicine"], e["instruction"])
                for e in entries
            ]
            block.append(_entry_table(rows, styles, with_time=True))
        else:
            block.append(Paragraph(schedule["empty_slot_note"], styles["small"]))
        story.append(KeepTogether(block))

    # ------------------------------------------------------------ as-needed
    if schedule["as_needed"]:
        block = [Paragraph(schedule["as_needed_heading"], styles["section"])]
        rows = [(e["medicine"], e["instruction"]) for e in schedule["as_needed"]]
        block.append(_entry_table(rows, styles, with_time=False))
        story.append(KeepTogether(block))

    # ------------------------------------------------- excluded warning box
    if schedule["excluded"]:
        box_content: list[Any] = [
            Paragraph(f"⚠ {schedule['excluded_heading']}", styles["warn_head"]),
            Paragraph(
                "We never guess. Confirm or edit these lines in MedRecall, "
                "then regenerate the timetable.",
                styles["warn_item"],
            ),
            Spacer(1, 4),
        ]
        for e in schedule["excluded"]:
            line_ref = f"Line {e['line_number']}: " if e.get("line_number") else ""
            box_content.append(Paragraph(
                f"• {line_ref}<b>{e['medicine'] or e['source_text'][:40]}</b> — {e['reason']}",
                styles["warn_item"],
            ))
        warning_box = Table([[box_content]], colWidths=[515])
        warning_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), AMBER_BG),
            ("BOX", (0, 0), (-1, -1), 1.2, AMBER_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(Spacer(1, 14))
        story.append(warning_box)

    # ---------------------------------------------------- closing disclaimer
    story.append(Spacer(1, 16))
    story.append(Paragraph(disclaimer, styles["small"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
