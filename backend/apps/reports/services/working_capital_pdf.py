# PDF of the dashboard's "Fond de roulement client" card (client request
# 2026-09-25): the operator picks which lines to keep (e.g. drop the
# supplier debts before handing it to someone) - a real structured document
# (reportlab), same masthead as every other PDF of this app. AR uses the
# French labels, the documented policy of profit_pdf.py.

import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import (
    DEFAULT_COMPANY_NAME,
    FOOTER_MARGIN,
    logo_image,
    numbered_canvas_cls,
    safe_text,
)
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
    "supplier_company_stock": ("Stock : stock entreprise", "Stock: company stock", "supplier_company_stock_value"),
    "supplier_in_transit": ("Stock : en cours", "Stock: in transit", "supplier_in_transit_value"),
    "supplier_reliquat": ("Stock : chez le fournisseur", "Stock: at the supplier", "supplier_reliquat_value"),
    "advances_paid": (
        "Avances versees", "Advances paid", "advances_paid",
    ),
    "unsold_costs": (
        "Frais de trajet engages", "Trip costs engaged", "unsold_costs",
    ),
    "supplier_debt": ("- Dettes fournisseurs", "- Supplier debts", "supplier_debt_total"),
    "transporter_debt": ("- Dettes transporteurs", "- Transporter debts", "transporter_debt_total"),
    "other_debts": ("- Dettes douane / transit / frais", "- Customs / transit / fees debts", "other_debts"),
}

_TITLES = {"fr": "Fond de roulement client", "en": "Customer working capital"}
_EXPORT_DATE = {"fr": "Date d'export", "en": "Export date"}

# The layout follows the client's own "Etat de la tresorerie" sheet: an orange
# title band, grey section bands, numbered rows (N | label | balance), a peach
# TOTAL row closing each section and an orange final row.
_ORANGE = colors.HexColor("#ED7D31")
_PEACH = colors.HexColor("#F8CBAD")
_GREY = colors.HexColor("#D9D9D9")

_SHEET_TEXT = {
    "fr": {
        "title": "ETAT DU FOND DE ROULEMENT",
        "number": "N",
        "label": "LIBELLE",
        "balance": "SOLDE (XOF)",
        "total": "TOTAL",
        "final": "FOND DE ROULEMENT",
        "treasury": "TRESORERIE",
        "receivables": "ETAT DES CREANCES",
        "stock": "STOCK FOURNISSEUR",
        "engaged": "AVANCES ET FRAIS ENGAGES",
        "debts": "DETTES (A DEDUIRE)",
        "info": "INFORMATIONS (NON INCLUSES DANS LE TOTAL)",
    },
    "en": {
        "title": "WORKING CAPITAL STATEMENT",
        "number": "N",
        "label": "DESCRIPTION",
        "balance": "BALANCE (XOF)",
        "total": "TOTAL",
        "final": "WORKING CAPITAL",
        "treasury": "TREASURY",
        "receivables": "CUSTOMER RECEIVABLES",
        "stock": "SUPPLIER STOCK",
        "engaged": "ADVANCES AND ENGAGED COSTS",
        "debts": "DEBTS (DEDUCTED)",
        "info": "INFORMATION (NOT IN THE TOTAL)",
    },
}

# section key -> the WORKING_CAPITAL_LINES keys it groups, in printed order.
_SECTIONS = (
    ("treasury", ("treasury",)),
    ("receivables", ("receivables",)),
    ("stock", ("supplier_company_stock", "supplier_in_transit", "supplier_reliquat")),
    ("engaged", ("advances_paid", "unsold_costs")),
    ("debts", ("supplier_debt", "transporter_debt", "other_debts")),
    ("info", ("capital", "shareholder_dues")),
)
_DEBT_KEYS = {"supplier_debt", "transporter_debt", "other_debts"}


def _number(value) -> str:
    """`1 908 543 007` / `-171 927 500`: the sheet prints bare figures (the
    unit is in the column header)."""
    return _format_money(value).replace(" XOF", "")


def render_working_capital_pdf(
    *,
    working_capital: dict,
    lines: list[str],
    lang: str = "fr",
    treasury_accounts: list[tuple[str, object]] | None = None,
    customer_receivables: list[tuple[str, object]] | None = None,
) -> bytes:
    """`lines`: the WORKING_CAPITAL_LINES keys to print; values read from
    `working_capital` (WorkingCapitalService.get_working_capital()), never
    recomputed here. `treasury_accounts` / `customer_receivables` (name,
    amount) detail the two lines like the client's sheet lists each bank and
    each customer; without them the line is printed as one row."""
    language = "en" if lang == "en" else "fr"
    label_index = 1 if language == "en" else 0
    text = _SHEET_TEXT[language]
    title = _TITLES[language]

    styles = getSampleStyleSheet()
    cell = ParagraphStyle("wcCell", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=TA_CENTER)
    amount_style = ParagraphStyle("wcAmount", parent=cell, alignment=TA_RIGHT)
    band = ParagraphStyle("wcBand", parent=cell, fontName="Helvetica-BoldOblique")

    def band_text(value: str) -> Paragraph:
        return Paragraph(f"<u>{safe_text(value)}</u>", band)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=FOOTER_MARGIN, title=title,
    )
    elements: list = []
    logo = logo_image()
    if logo is not None:
        elements.append(logo)
        elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(safe_text(DEFAULT_COMPANY_NAME), styles["Title"]))
    elements.append(
        Paragraph(f"{_EXPORT_DATE[language]}: {datetime.date.today().isoformat()}", styles["Normal"])
    )
    elements.append(Spacer(1, 6 * mm))

    rows: list = [[band_text(f"{text['title']} - {DEFAULT_COMPANY_NAME}"), "", ""]]
    style: list = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), _ORANGE),
        ("BOX", (0, 0), (-1, -1), 1, colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]

    def add_banner(label: str, color):
        rows.append([band_text(label), "", ""])
        index = len(rows) - 1
        style.extend([("SPAN", (0, index), (-1, index)), ("BACKGROUND", (0, index), (-1, index), color)])

    # Column headers (peach), like the sheet's "N | BANQUE | SOLDE" row.
    rows.append([Paragraph(text["number"], cell), Paragraph(text["label"], cell), Paragraph(text["balance"], cell)])
    style.append(("BACKGROUND", (0, 1), (-1, 1), _PEACH))

    counter = 0

    def add_row(label: str, amount, *, color=None):
        nonlocal counter
        counter += 1
        rows.append([Paragraph(str(counter), cell), Paragraph(safe_text(label), cell), Paragraph(_number(amount), amount_style)])
        if color is not None:
            style.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), color))

    def add_section(section, keys):
        chosen = [key for key in keys if key in lines]
        if not chosen:
            return
        add_banner(text[section], _GREY)
        printed: list = []
        for key in chosen:
            label = WORKING_CAPITAL_LINES[key][label_index].lstrip("- ").strip()
            value = working_capital[WORKING_CAPITAL_LINES[key][2]]
            signed = -value if key in _DEBT_KEYS else value
            detail = None
            if key == "treasury":
                detail = treasury_accounts
            elif key == "receivables":
                detail = customer_receivables
            if detail:
                for name, amount in detail:
                    add_row(name, amount)
                    printed.append(amount)
            else:
                add_row(label, signed)
                printed.append(signed)
        if section != "info" and len(printed) > 1:
            add_row(text["total"], sum(printed, 0), color=_PEACH)

    for section, keys in _SECTIONS:
        if section != "info":
            add_section(section, keys)

    if "total" in lines:
        add_row(text["final"], working_capital["total"], color=_ORANGE)

    for section, keys in _SECTIONS:
        if section == "info":
            add_section(section, keys)

    table = Table(rows, colWidths=[14 * mm, 112 * mm, 44 * mm], repeatRows=2)
    table.setStyle(TableStyle(style))
    elements.append(table)
    doc.build(elements, canvasmaker=numbered_canvas_cls(running_title=f"{DEFAULT_COMPANY_NAME} — {title}", lang=language, side_margin=20 * mm))
    return buffer.getvalue()
