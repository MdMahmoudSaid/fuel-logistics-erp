# PDF of the dashboard's "Fond de roulement client" card (client request
# 2026-09-25): the operator picks which lines to keep (e.g. drop the
# supplier debts before handing it to someone) - a real structured document
# (reportlab), same masthead as every other PDF of this app. AR uses the
# French labels, the documented policy of profit_pdf.py.

import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME, masthead, safe_text
from apps.reports.services.profit_pdf import _format_money

# key -> (French label, English label, working_capital key). Order = order
# printed, same as the card on the dashboard.
WORKING_CAPITAL_LINES = {
    "total": ("Fond de roulement client", "Working capital", "total"),
    "capital": ("Capital apporte (information)", "Capital contributed (information)", "capital"),
    "shareholder_dues": (
        "Dues aux associes (information)", "Owed to shareholders (information)", "shareholder_dues",
    ),
    "treasury": ("Tresorerie disponible", "Available treasury", "treasury_available"),
    "receivables": ("Creances clients", "Customer receivables", "customer_receivables"),
    "supplier_debt": ("Dettes fournisseurs", "Supplier debts", "supplier_debt_total"),
    "transporter_debt": ("Dettes transporteurs", "Transporter debts", "transporter_debt_total"),
    "other_debts": ("Dettes douane / transit / frais", "Customs / transit / fees debts", "other_debts"),
    "supplier_company_stock": ("Paye : stock entreprise", "Paid: company stock", "supplier_company_stock_value"),
    "supplier_in_transit": ("Paye : en cours", "Paid: in transit", "supplier_in_transit_value"),
    "supplier_reliquat": ("Paye : chez le fournisseur", "Paid: at the supplier", "supplier_reliquat_value"),
}

_TITLES = {"fr": "Fond de roulement client", "en": "Customer working capital"}
_EXPORT_DATE = {"fr": "Date d'export", "en": "Export date"}


def render_working_capital_pdf(*, working_capital: dict, lines: list[str], lang: str = "fr") -> bytes:
    """`lines`: the WORKING_CAPITAL_LINES keys to print (order taken from
    WORKING_CAPITAL_LINES, not from the caller); values read from
    `working_capital` (WorkingCapitalService.get_working_capital()), never
    recomputed here."""
    language = "en" if lang == "en" else "fr"
    label_index = 1 if language == "en" else 0
    title = _TITLES[language]

    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle("wcHeading", parent=styles["Heading2"])
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm, title=title,
    )
    elements: list = masthead(
        company_name=DEFAULT_COMPANY_NAME, doc_title=title, styles=styles, heading_style=heading_style
    )
    elements.append(
        Paragraph(f"{_EXPORT_DATE[language]}: {datetime.date.today().isoformat()}", styles["Normal"])
    )
    elements.append(Spacer(1, 6 * mm))

    keys = [key for key in WORKING_CAPITAL_LINES if key in lines]
    rows = [
        (safe_text(WORKING_CAPITAL_LINES[key][label_index]), _format_money(working_capital[WORKING_CAPITAL_LINES[key][2]]))
        for key in keys
    ]
    table = Table(rows, colWidths=[105 * mm, 65 * mm])
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]
    if keys and keys[0] == "total":
        style.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f6f4ef")))
    table.setStyle(TableStyle(style))
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()
