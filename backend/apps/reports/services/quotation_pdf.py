# PDF export for a commercial quotation ("Offre commerciale" / "Devis") -
# AZUR ÉNERGIE product decision 2026-09-05. Export/formatting only: prints
# the already-saved Quotation/QuotationLine rows, no calculation beyond
# what QuotationSerializer already computed and persisted (total_amount,
# each line's line_total). Deliberately its own module rather than added
# to ledger_pdf.py - a quotation is not a party ledger, and this is the
# first PDF in the app to embed the AZUR ÉNERGIE logo image (the other
# PDFs stay text-only for this pass, see the rebrand commit).

import datetime
import io
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "azur-energie-icon.png"

QUOTATION_PDF_LABELS = {
    "fr": {
        "title": "Offre commerciale",
        "reference": "Reference",
        "customer": "Client",
        "issue_date": "Date d'emission",
        "validity_date": "Date de validite",
        "status": "Statut",
        "product": "Produit",
        "description": "Description",
        "quantity": "Quantite",
        "unit": "Unite",
        "unit_price": "Prix unitaire",
        "line_total": "Montant",
        "total": "Total",
        "notes": "Notes et conditions",
        "export_date": "Date d'export",
    },
    "en": {
        "title": "Commercial offer",
        "reference": "Reference",
        "customer": "Customer",
        "issue_date": "Issue date",
        "validity_date": "Validity date",
        "status": "Status",
        "product": "Product",
        "description": "Description",
        "quantity": "Quantity",
        "unit": "Unit",
        "unit_price": "Unit price",
        "line_total": "Amount",
        "total": "Total",
        "notes": "Notes and terms",
        "export_date": "Export date",
    },
    # AR: labels intentionally kept in French, same documented policy as
    # ledger_pdf.py (no embedded Arabic-capable font/shaping installed).
    "ar": {
        "title": "Offre commerciale",
        "reference": "Reference",
        "customer": "Client",
        "issue_date": "Date d'emission",
        "validity_date": "Date de validite",
        "status": "Statut",
        "product": "Produit",
        "description": "Description",
        "quantity": "Quantite",
        "unit": "Unite",
        "unit_price": "Prix unitaire",
        "line_total": "Montant",
        "total": "Total",
        "notes": "Notes et conditions",
        "export_date": "Date d'export",
    },
}

STATUS_LABELS_FR = {
    "DRAFT": "Brouillon",
    "SENT": "Envoyee",
    "ACCEPTED": "Acceptee",
    "REJECTED": "Refusee",
    "EXPIRED": "Expiree",
}

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12171c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f4ef")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]
)

_SUMMARY_TABLE_STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
)


def _stringify(value, lang: str = "fr") -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    text = str(value)
    if lang in ("fr", "ar") and text in STATUS_LABELS_FR:
        return STATUS_LABELS_FR[text]
    return text


def _labels(lang: str) -> dict:
    return QUOTATION_PDF_LABELS.get(lang, QUOTATION_PDF_LABELS["fr"])


def render_quotation_pdf(quotation, lang: str = "fr") -> bytes:
    """Single-document PDF: AZUR ÉNERGIE header (with logo), quotation
    header fields (reference/client/dates/status), the line-items table,
    the total, and notes/terms - "create/save/edit/duplicate/preview/
    print/PDF" (product decision 2026-09-05, quotation page spec)."""
    labels = _labels(lang)
    is_rtl = lang == "ar"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{labels['title']} - {quotation.reference}",
    )
    styles = getSampleStyleSheet()
    align_style = ParagraphStyle("aligned", parent=styles["Normal"], alignment=TA_RIGHT if is_rtl else 0)
    heading_style = ParagraphStyle(
        "headingAligned", parent=styles["Heading2"], alignment=TA_RIGHT if is_rtl else 0
    )

    elements: list = []
    if _LOGO_PATH.exists():
        logo = Image(str(_LOGO_PATH), width=18 * mm, height=18 * mm)
        logo.hAlign = "RIGHT" if is_rtl else "LEFT"
        elements.append(logo)
        elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(DEFAULT_COMPANY_NAME, styles["Title"]))
    elements.append(Paragraph(f"{labels['title']} - {quotation.reference}", heading_style))
    elements.append(Spacer(1, 6 * mm))

    header_rows = [
        (labels["reference"], quotation.reference),
        (labels["customer"], quotation.customer_display_name),
        (labels["issue_date"], quotation.issue_date),
        (labels["validity_date"], quotation.validity_date),
        (labels["status"], quotation.status),
    ]
    header_data = [[label, _stringify(value, lang)] for label, value in header_rows]
    if is_rtl:
        header_data = [list(reversed(row)) for row in header_data]
    header_table = Table(header_data, colWidths=[45 * mm, 115 * mm])
    header_table.setStyle(_SUMMARY_TABLE_STYLE)
    elements.append(header_table)
    elements.append(Spacer(1, 8 * mm))

    lines = list(quotation.lines.all())
    if lines:
        field_order = ["product", "description", "quantity", "unit", "unit_price", "line_total"]
        table_header = [labels[f] for f in field_order]
        rows = []
        for line in lines:
            product_name = line.product.name if line.product_id else ""
            rows.append(
                [
                    product_name,
                    line.description,
                    _stringify(line.quantity, lang),
                    line.unit,
                    _stringify(line.unit_price, lang),
                    _stringify(line.line_total, lang),
                ]
            )
        if is_rtl:
            table_header = list(reversed(table_header))
            rows = [list(reversed(row)) for row in rows]
        table_data = [table_header] + rows
        items_table = Table(table_data, repeatRows=1)
        items_table.setStyle(_TABLE_STYLE)
        elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    total_data = [[labels["total"], _stringify(quotation.total_amount, lang) + f" {quotation.currency}"]]
    if is_rtl:
        total_data = [list(reversed(row)) for row in total_data]
    total_table = Table(total_data, colWidths=[45 * mm, 115 * mm])
    total_table.setStyle(_SUMMARY_TABLE_STYLE)
    elements.append(total_table)

    if quotation.notes:
        elements.append(Spacer(1, 8 * mm))
        elements.append(Paragraph(labels["notes"], heading_style))
        elements.append(Spacer(1, 2 * mm))
        # Security fix: quotation.notes is free-form user input (the
        # "Notes / conditions" textarea) - reportlab's Paragraph parses a
        # mini-XML/HTML markup language, including <img src="..."> tags
        # that reportlab resolves as a real file/URL fetch at render time
        # (SSRF/LFI), plus arbitrary formatting/link injection. Escape the
        # raw text first (neutralizes any embedded tags/entities), then
        # apply our own literal <br/> line breaks on the now-safe string -
        # never on unescaped user input.
        safe_notes = xml_escape(quotation.notes).replace("\n", "<br/>")
        elements.append(Paragraph(safe_notes, align_style))

    elements.append(Spacer(1, 8 * mm))
    elements.append(
        Paragraph(f"{labels['export_date']}: {datetime.date.today().isoformat()}", styles["Normal"])
    )

    doc.build(elements)
    return buffer.getvalue()
