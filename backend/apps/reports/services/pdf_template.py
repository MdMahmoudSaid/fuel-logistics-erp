# Building blocks shared by every PDF this app renders (docs/superpowers/
# specs/2026-09-23-rapports-document-comptable-design.md, section pdf_template):
# company constant, logo, free-text escaping and the logo + company + title
# masthead. ledger_pdf, profit_pdf, quotation_pdf and report_pdf all import
# from here instead of each carrying its own copy.

from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.units import mm
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


def para_text(value, lang: str = "fr") -> str:
    """Text ready to be placed in a Paragraph: escaped user content. (Arabic
    shaping/bidi and font-run wrapping are added here in the Arabic block.)"""
    return safe_text(value)


def numbered_canvas_cls(*, running_title: str, page_label: str, lang: str = "fr"):
    """Canvas class that stamps "Page n / N" at the bottom of every page and
    the running title at the top of pages 2+ (two-pass: N is only known once
    every page has been laid out)."""
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
            self.setFont("Helvetica", 7)
            self.drawCentredString(
                width / 2, 7 * mm, page_label.format(n=number, total=total)
            )
            if number > 1:
                self.drawString(12 * mm, height - 8 * mm, running_title)

    return NumberedCanvas
