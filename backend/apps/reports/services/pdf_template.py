# Building blocks shared by every PDF this app renders (docs/superpowers/
# specs/2026-09-23-rapports-document-comptable-design.md, section pdf_template):
# company constant, logo, free-text escaping and the logo + company + title
# masthead. ledger_pdf, profit_pdf, quotation_pdf and report_pdf all import
# from here instead of each carrying its own copy.

import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import arabic_reshaper
from bidi import get_display
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, Spacer

# No per-tenant "company name" setting exists anywhere in this codebase - a
# fixed constant is used for every PDF header (rebrand 2026-09-05: AZUR
# ÉNERGIE, no "ERP" suffix on PDFs).
DEFAULT_COMPANY_NAME = "AZUR ÉNERGIE"

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "azur-energie-icon.png"


def safe_text(value) -> str:
    """Escape free-text before it reaches a reportlab Paragraph.

    Paragraph parses a mini-XML/HTML markup language, including <img src=...>
    tags that reportlab resolves as a real file/URL fetch at render time
    (SSRF/LFI), plus link/format injection and parse crashes on an unbalanced
    "<" or "&" (security fix 2026-09-06). Every operator-typed value (party
    names, notes, references) wrapped in a Paragraph must go through here; a
    bare str in a plain Table cell is never markup-parsed and needs none."""
    return xml_escape(str(value)) if value is not None else ""


def logo_image(size=18 * mm):
    """The logo flowable, or None when the file is missing (a missing logo
    never blocks an export)."""
    return Image(str(LOGO_PATH), width=size, height=size) if LOGO_PATH.exists() else None


def masthead(*, company_name: str, doc_title: str, styles, heading_style) -> list:
    """Logo + company name + document-title heading (the stacked masthead of
    the party-ledger and profit PDFs)."""
    elements: list = []
    logo = logo_image()
    if logo is not None:
        elements.append(logo)
        elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(safe_text(company_name), styles["Title"]))
    elements.append(Paragraph(safe_text(doc_title), heading_style))
    return elements


_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
ARABIC_FONT = "NotoNaskhArabic"
ARABIC_FONT_BOLD = "NotoNaskhArabic-Bold"
# Noto Naskh Arabic has Arabic-script glyphs (plus digits and space) but no
# Latin letters or "/", "-", "(" ...: only Arabic-script runs are drawn with
# it, everything else (Latin, digits, punctuation, "XOF") keeps Helvetica.
_ARABIC_RUN = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+")


def _register_arabic_fonts() -> None:
    if ARABIC_FONT in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(ARABIC_FONT, str(_FONT_DIR / "NotoNaskhArabic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(ARABIC_FONT_BOLD, str(_FONT_DIR / "NotoNaskhArabic-Bold.ttf")))
    pdfmetrics.registerFontFamily(
        ARABIC_FONT, normal=ARABIC_FONT, bold=ARABIC_FONT_BOLD, italic=ARABIC_FONT, boldItalic=ARABIC_FONT_BOLD
    )


_register_arabic_fonts()


def has_arabic(text: str) -> bool:
    return bool(_ARABIC_RUN.search(text))


def _base_direction(text: str) -> str:
    """'R' when the first strong character is Arabic-script (paragraph reads
    right-to-left), else 'L'."""
    for char in text:
        if _ARABIC_RUN.match(char):
            return "R"
        if char.isalpha():
            return "L"
    return "L"


_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")


def _display(line: str, base: str) -> str:
    """Bidi-order one logical line. python-bidi does not mirror brackets, so
    in a right-to-left line they are swapped here (otherwise "(لتر)" would be
    drawn as ")لتر(")."""
    visual = get_display(line, base_dir=base)
    return visual.translate(_MIRROR) if base == "R" else visual


def _run_width(text: str, size: float, bold: bool) -> float:
    latin = "Helvetica-Bold" if bold else "Helvetica"
    arabic = ARABIC_FONT_BOLD if bold else ARABIC_FONT
    total, position = 0.0, 0
    for match in _ARABIC_RUN.finditer(text):
        total += pdfmetrics.stringWidth(text[position : match.start()], latin, size)
        total += pdfmetrics.stringWidth(match.group(), arabic, size)
        position = match.end()
    return total + pdfmetrics.stringWidth(text[position:], latin, size)


def _wrap_logical(shaped: str, width: float, size: float, bold: bool) -> list[str]:
    """Greedy line breaking on the reshaped text in LOGICAL order (each line
    is bidi-ordered afterwards - wrapping a visually reordered string would
    put the end of the sentence on the first line)."""
    lines: list[str] = []
    current = ""
    for word in shaped.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and _run_width(candidate, size, bold) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    return lines


def _font_runs(escaped: str, bold: bool) -> str:
    font = ARABIC_FONT_BOLD if bold else ARABIC_FONT
    return _ARABIC_RUN.sub(lambda m: f'<font name="{font}">{m.group()}</font>', escaped)


def visual_text(text: str) -> str:
    """Reshaped + bidi-ordered string (what is actually drawn) for text that
    contains Arabic script; anything else is returned untouched."""
    if not has_arabic(text):
        return text
    return _display(arabic_reshaper.reshape(text), _base_direction(text))


def para_text(value, lang: str = "fr", *, bold: bool = False, width: float | None = None, size: float = 8) -> str:
    """Text ready to be placed in a Paragraph: escaped user content, and -
    when it contains Arabic script, whatever the document language - shaped,
    bidi-ordered and drawn with Noto Naskh. `width` (points) makes Arabic text
    wrap line by line in logical order; Latin/number text is returned escaped
    and unchanged (Paragraph wraps it itself)."""
    if value is None:
        return ""
    text = str(value)
    if not has_arabic(text):
        return safe_text(text)
    shaped = arabic_reshaper.reshape(text)
    base = _base_direction(text)
    lines = _wrap_logical(shaped, width, size, bold) if width else [shaped]
    return "<br/>".join(_font_runs(xml_escape(_display(line, base)), bold) for line in lines)


def draw_text(canvas, x: float, y: float, text: str, *, size: float = 7, align: str = "left", bold: bool = False):
    """Draw one line on a canvas, switching font per run (Arabic -> Noto, the
    rest Helvetica); `align` is left | center | right relative to x."""
    visual = visual_text(text)
    width = _run_width(visual, size, bold)
    cursor = x - (width / 2 if align == "center" else width if align == "right" else 0)
    latin = "Helvetica-Bold" if bold else "Helvetica"
    arabic = ARABIC_FONT_BOLD if bold else ARABIC_FONT
    pieces, position = [], 0
    for match in _ARABIC_RUN.finditer(visual):
        pieces += [(visual[position : match.start()], latin), (match.group(), arabic)]
        position = match.end()
    pieces.append((visual[position:], latin))
    for chunk, font in pieces:
        if chunk:
            canvas.setFont(font, size)
            canvas.drawString(cursor, y, chunk)
            cursor += pdfmetrics.stringWidth(chunk, font, size)


def numbered_canvas_cls(*, running_title: str, page_label: str, lang: str = "fr"):
    """Canvas class that stamps "Page n / N" at the bottom of every page and
    the running title at the top of pages 2+ (two-pass: N is only known once
    every page has been laid out). In Arabic the title sits on the right."""
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages: list[dict] = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self._decorate(self._pageNumber, total)
                super().showPage()
            super().save()

        def _decorate(self, number: int, total: int):
            width, height = self._pagesize
            self.setFillColor(colors.HexColor("#6b7280"))
            draw_text(self, width / 2, 7 * mm, page_label.format(n=number, total=total), align="center")
            if number > 1:
                if lang == "ar":
                    draw_text(self, width - 12 * mm, height - 8 * mm, running_title, align="right")
                else:
                    draw_text(self, 12 * mm, height - 8 * mm, running_title)

    return NumberedCanvas
