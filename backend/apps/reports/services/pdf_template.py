# Building blocks shared by every PDF this app renders (docs/superpowers/
# specs/2026-09-23-rapports-document-comptable-design.md, section pdf_template):
# company constant, logo, free-text escaping and the logo + company + title
# masthead. ledger_pdf, profit_pdf, proforma_pdf and report_pdf all import
# from here instead of each carrying its own copy.

import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import arabic_reshaper
from bidi import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Image, Paragraph, Spacer, Table, TableStyle

from apps.core.brand import BRAND_LOGO_PATH, BRAND_NAME

# The name/logo of every PDF header come from the installation's brand
# (BRAND env var, see apps/core/brand.py); no "ERP" suffix on PDFs.
DEFAULT_COMPANY_NAME = BRAND_NAME

LOGO_PATH = BRAND_LOGO_PATH


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
    """The logo flowable fitted in a `size` square (aspect ratio kept), or
    None when the file is missing (a missing logo never blocks an export)."""
    if not LOGO_PATH.exists():
        return None
    try:
        pixel_w, pixel_h = ImageReader(str(LOGO_PATH)).getSize()
    except Exception:
        return Image(str(LOGO_PATH), width=size, height=size)
    scale = size / max(pixel_w, pixel_h)
    return Image(str(LOGO_PATH), width=pixel_w * scale, height=pixel_h * scale)


def masthead(*, company_name: str, doc_title: str, styles, heading_style, width: float = A4[0] - 30 * mm) -> list:
    """Letterhead (logo + company name + contact details + blue rule) followed
    by the document-title heading, for the flowable-based PDFs (profit, ...)."""
    elements = letterhead(width, company_name=company_name)
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(safe_text(doc_title), heading_style))
    return elements


_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
ARABIC_FONT = "NotoNaskhArabic"
ARABIC_FONT_BOLD = "NotoNaskhArabic-Bold"
# Noto Naskh Arabic has Arabic-script glyphs (plus digits and space) but no
# Latin letters or "/", "-", "(" ...: only Arabic-script runs are drawn with
# it, everything else (Latin, digits, punctuation, "XOF") keeps the Latin family.
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

# One Latin family for every PDF: Source Sans 3 (SIL OFL, assets/fonts) - its
# SemiBold is what "bold" means everywhere, so titles, labels and totals share
# the same weight.
SANS = "SourceSans3"
SANS_BOLD = "SourceSans3-Semibold"


def _register_sans_fonts() -> None:
    if SANS in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(SANS, str(_FONT_DIR / "SourceSans3-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(SANS_BOLD, str(_FONT_DIR / "SourceSans3-Semibold.ttf")))
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_BOLD, italic=SANS, boldItalic=SANS_BOLD)


_register_sans_fonts()


def sans_styles():
    """reportlab's sample stylesheet re-based on the shared family."""
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        if not hasattr(style, "fontName"):
            continue
        style.fontName = SANS_BOLD if "Bold" in style.fontName else SANS
    return styles


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
    latin = SANS_BOLD if bold else SANS
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
    rest Source Sans); `align` is left | center | right relative to x."""
    visual = visual_text(text)
    width = _run_width(visual, size, bold)
    cursor = x - (width / 2 if align == "center" else width if align == "right" else 0)
    latin = SANS_BOLD if bold else SANS
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


INK = colors.HexColor("#111827")
NAVY = colors.HexColor("#0f2747")
CONTACT_GREY = colors.HexColor("#4b5563")
LABEL_GREY = colors.HexColor("#6b7280")
BRAND_BLUE = colors.HexColor("#0b5cab")
RULE_GREY = colors.HexColor("#d1d5db")

_PAGE_LABELS = {"fr": "Page {n} / {total}", "en": "Page {n} / {total}", "ar": "صفحة {n} / {total}"}
_BANK_TITLES = {"fr": "COORDONNÉES BANCAIRES", "en": "BANK DETAILS", "ar": "البيانات المصرفية"}
_ACCOUNT_LABEL = {"fr": "Compte", "en": "Account", "ar": "الحساب"}
_BRAND_BAR = (("#0b5cab", 0.7), ("#1e90d6", 0.2), ("#f39200", 0.1))

NAME_SIZE = 19
CONTACT_SIZE = 9
FOOTER_SIZE = 9
FOOTER_TITLE_SIZE = 8
_FOOTER_LINE = 4.3 * mm
_FOOTER_BOTTOM = 10 * mm  # last footer baseline sits ~10 mm above the sheet edge
_BAR_HEIGHT = 1.6 * mm
MAX_FOOTER_BANKS = 6


def _company_profile_block() -> dict:
    """The company block of the Informations de l'entreprise page. Like the
    logo, a profile problem never blocks an export."""
    try:
        from apps.core.models import CompanyProfile

        return CompanyProfile.load().pdf_company()
    except Exception:
        return {"name": DEFAULT_COMPANY_NAME, "lines": [], "contact": [], "banks": []}


def company_display_name(fallback: str | None = None) -> str:
    """Name printed in every letterhead: the one saved in the Informations de
    l'entreprise page, spelled as saved (brand name only while it is empty)."""
    return (_company_profile_block().get("name") or "").strip() or fallback or DEFAULT_COMPANY_NAME


def company_contact_lines() -> list[str]:
    """One line per fact - address, phones, e-mail, website, NIF / RC; absent
    fields are simply missing."""
    return list(_company_profile_block().get("contact") or [])


def letterhead(width: float, *, company_name: str | None = None, tagline: str | None = None,
               lang: str = "fr", rtl: bool = False) -> list:
    """Shared header of every PDF, two blocks across the content width: logo +
    company name (19 pt, navy) on the leading side, contact details opposite
    (9 pt, right-aligned, vertically centred), then a thin rule in the logo
    blue. Mirrored in Arabic."""
    name = company_display_name(company_name)
    name_style = ParagraphStyle("lhName", fontName=SANS_BOLD, fontSize=NAME_SIZE, leading=NAME_SIZE * 1.15,
                                textColor=NAVY, alignment=TA_RIGHT if rtl else TA_LEFT)
    contact_style = ParagraphStyle("lhContact", fontName=SANS, fontSize=CONTACT_SIZE, leading=CONTACT_SIZE * 1.3,
                                   textColor=CONTACT_GREY, alignment=TA_LEFT if rtl else TA_RIGHT)
    tagline_style = ParagraphStyle("lhTagline", parent=contact_style, alignment=name_style.alignment)

    gap = 4 * mm  # logo <-> name
    logo_box = 20 * mm
    logo = logo_image(logo_box)
    logo_w = logo_box + gap if logo is not None else 0
    lines = company_contact_lines()
    widest = max((_run_width(visual_text(line), CONTACT_SIZE, False) for line in lines), default=0)
    # Contact block: as wide as its longest line, but never more than half of
    # the header, so a long name keeps room (it wraps on its own lines).
    contact_w = min(widest + 3 * mm, (width - logo_w) * 0.5) if lines else 0
    name_w = width - logo_w - contact_w

    name_cell = [Paragraph(para_text(name, lang, bold=True, size=NAME_SIZE), name_style)]
    if tagline:
        name_cell.append(Paragraph(para_text(tagline, lang, size=CONTACT_SIZE), tagline_style))
    contact_cell = [Paragraph(para_text(line, lang, size=CONTACT_SIZE, width=contact_w), contact_style) for line in lines]

    cells, widths = [], []
    if logo is not None:
        cells.append(logo)
        widths.append(logo_w)
    cells.append(name_cell)
    widths.append(name_w)
    if lines:
        cells.append(contact_cell)
        widths.append(contact_w)
    if rtl:
        cells, widths = cells[::-1], widths[::-1]
    head = Table([cells], colWidths=widths)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if logo is not None:  # the 4 mm gap sits on the logo's inner side
        style.append(("ALIGN", (-1 if rtl else 0, 0), (-1 if rtl else 0, 0), "RIGHT" if rtl else "LEFT"))
        style.append(("RIGHTPADDING" if not rtl else "LEFTPADDING", (-1 if rtl else 0, 0), (-1 if rtl else 0, 0), gap))
    head.setStyle(TableStyle(style))
    return [head, Spacer(1, 5 * mm), HRFlowable(width=width, thickness=1, color=BRAND_BLUE, spaceAfter=0, hAlign="CENTER")]


def _bank_lines(bank: dict, usable: float, lang: str) -> list[list[tuple[str, bool]]]:
    """One account as footer lines of (text, bold) runs: bank name in bold,
    then "Compte : n" and "SWIFT : code" after " | ". When it does not fit,
    it breaks at those separators (then at spaces) - values stay complete."""
    tokens = [(bank["bank"], True), (f"{_ACCOUNT_LABEL.get(lang, 'Account')} : {bank['account']}", False)]
    if bank.get("swift"):
        tokens.append((f"SWIFT : {bank['swift']}", False))
    separator = "  |  "
    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    used = 0.0
    for text, bold in tokens:
        width = _run_width(visual_text(text), FOOTER_SIZE, bold)
        extra = _run_width(separator, FOOTER_SIZE, False) if current else 0
        if current and used + extra + width > usable:
            lines.append(current)
            current, used, extra = [], 0.0, 0.0
        if width > usable:  # a single very long value: wrap on spaces
            wrapped = _wrap_logical(text, usable, FOOTER_SIZE, bold)
            lines.extend([[(piece, bold)] for piece in wrapped[:-1]])
            text, width = wrapped[-1], _run_width(visual_text(wrapped[-1]), FOOTER_SIZE, bold)
        if current:
            current.append((separator, False))
        current.append((text, bold))
        used += extra + width
    lines.append(current)
    return lines


def footer_lines(usable: float, lang: str = "fr") -> list[list[tuple[str, bool]]]:
    """Every bank account of the company profile as footer lines."""
    lines: list[list[tuple[str, bool]]] = []
    for bank in (_company_profile_block().get("banks") or [])[:MAX_FOOTER_BANKS]:
        lines.extend(_bank_lines(bank, usable, lang))
    return lines


def footer_margin(side_margin: float = 12 * mm, page_width: float = A4[0], lang: str = "fr") -> float:
    """Bottom margin a PDF reserves for the footer: ~10 mm of sheet margin, the
    title line, one line per bank-account line (computed on a portrait A4
    width, so wider pages only gain room) and a clear gap above the hairline."""
    count = len(footer_lines(page_width - 2 * side_margin, lang))
    return _FOOTER_BOTTOM + _FOOTER_LINE * (1 + count) + 3 * mm + 5 * mm


def _draw_runs(canvas, x: float, baseline: float, runs: list[tuple[str, bool]], *, rtl: bool):
    """A line of mixed-weight runs from the leading margin (right edge in
    Arabic, where the runs also run right to left)."""
    ordered = runs[::-1] if rtl else runs
    cursor = x
    for text, bold in ordered:
        width = _run_width(visual_text(text), FOOTER_SIZE, bold)
        canvas.setFillColor(INK if bold else colors.HexColor("#374151"))
        draw_text(canvas, cursor, baseline, text, size=FOOTER_SIZE, align="right" if rtl else "left", bold=bold)
        cursor += -width if rtl else width


def draw_company_footer(canvas, *, number: int, total: int, page_label: str, lang: str, side_margin: float):
    """Footer of one page, in the reserved bottom zone: brand colour bar, a
    light hairline, the title "COORDONNÉES BANCAIRES" (small, bold, blue) with
    "Page n / N" opposite it - on the title line only, so it never meets a
    bank line - then one line per account. Same margins as the header;
    mirrored in Arabic. Contact details live in the header."""
    width = canvas._pagesize[0]
    rtl = lang == "ar"
    lines = footer_lines(width - 2 * side_margin, lang)

    x = 0.0
    for color, share in _BRAND_BAR:
        canvas.setFillColor(colors.HexColor(color))
        canvas.rect(x, 0, width * share, _BAR_HEIGHT, stroke=0, fill=1)
        x += width * share

    last_baseline = _FOOTER_BOTTOM
    title_baseline = last_baseline + _FOOTER_LINE * len(lines)
    rule_y = title_baseline + 3 * mm
    canvas.setStrokeColor(RULE_GREY)
    canvas.setLineWidth(0.5)
    canvas.line(side_margin, rule_y, width - side_margin, rule_y)

    text_x = width - side_margin if rtl else side_margin
    align = "right" if rtl else "left"
    if lines:
        canvas.setFillColor(BRAND_BLUE)
        draw_text(canvas, text_x, title_baseline, _BANK_TITLES.get(lang, _BANK_TITLES["fr"]),
                  size=FOOTER_TITLE_SIZE, align=align, bold=True)
    canvas.setFillColor(CONTACT_GREY)
    draw_text(
        canvas, width - text_x, title_baseline, page_label.format(n=number, total=total),
        size=FOOTER_SIZE, align="left" if rtl else "right",
    )
    for index, runs in enumerate(lines):
        _draw_runs(canvas, text_x, title_baseline - _FOOTER_LINE * (index + 1), runs, rtl=rtl)


def numbered_canvas_cls(*, running_title: str, page_label: str | None = None, lang: str = "fr", side_margin: float = 12 * mm):
    """Canvas class that stamps the company footer (and "Page n / N") at the
    bottom of every page and the running title at the top of pages 2+
    (two-pass: N is only known once every page has been laid out). In Arabic
    the title sits on the right."""
    from reportlab.pdfgen import canvas

    label = page_label or _PAGE_LABELS.get(lang, _PAGE_LABELS["fr"])

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
            draw_company_footer(
                self, number=number, total=total, page_label=label, lang=lang, side_margin=side_margin
            )
            self.setFillColor(colors.HexColor("#6b7280"))
            if number > 1:
                if lang == "ar":
                    draw_text(self, width - 12 * mm, height - 8 * mm, running_title, align="right")
                else:
                    draw_text(self, 12 * mm, height - 8 * mm, running_title)

    return NumberedCanvas
