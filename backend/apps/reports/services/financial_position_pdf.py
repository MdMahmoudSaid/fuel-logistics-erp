# PDF of the "Situation financiere" page (client request 2026-10-17): what the
# company owns / owes / the net result, with the same figures as the page
# (FinancialPositionService.get_position(), never recomputed here) and the same
# masthead as every other PDF of this app. AR uses the French labels, the
# documented policy of profit_pdf.py / working_capital_pdf.py.

import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME, masthead, safe_text
from apps.reports.services.profit_pdf import _format_money

LABELS = {
    "fr": {
        "title": "Situation financiere",
        "export_date": "Date d'export",
        "assets": "Ce que possede l'entreprise",
        "liabilities": "Ce que doit l'entreprise",
        "total_assets": "Total de ce que possede l'entreprise",
        "total_liabilities": "Total de ce que doit l'entreprise",
        "net_result": "Resultat net",
        "net_help": "Ce que possede l'entreprise - ce qu'elle doit (associes et fonds de depart compris). "
        "C'est le benefice net a distribuer.",
        "control": "Controle : benefice net a distribuer (page Benefices)",
        "control_ok": "Identique au resultat net",
        "control_gap": "Ecart avec le resultat net",
        "note": "Les dettes sont affichees pour leur montant complet, comme dans le Fond de roulement. "
        "Le carburant et les frais d'un trajet non encore vendu, pas encore payes, figurent des deux "
        "cotes (l'actif finance par la dette) : ils s'annulent dans le resultat net.",
        "capital": "Capital apporte (information)",
        "lines": {
            "banks": "Banques",
            "cash": "Caisses",
            "customer_receivables": "Creances clients",
            "supplier_advances": "Avances versees aux fournisseurs",
            "transporter_advances": "Avances versees aux transporteurs",
            "associate_advances": "Avances aux associes (non recuperees)",
            "supplier_debts": "Dettes fournisseurs",
            "transporter_debts": "Dettes transporteurs",
            "trip_fee_debts": "Dettes douane / transit / frais",
            "customer_credit": "Avances recues des clients",
            "shareholder_dues": "Du aux associes (capital et benefices non retires)",
            "unsold_fuel_paid": "Carburant non vendu deja paye",
            "unsold_costs_paid": "Frais de trajet payes sur du carburant non vendu",
            "starting_funds": "Fonds de depart (soldes d'ouverture et anciennes dettes)",
            "unsold_unpaid_covered": "Carburant non vendu, non encore paye (couvert par les dettes)",
        },
        "children": {
            "company_stock": "Paye : stock entreprise",
            "in_transit": "Paye : en cours",
            "at_supplier": "Paye : chez le fournisseur",
            "customs": "Douane",
            "transit": "Transit",
            "road_transit": "Transit routiere",
            "border": "Frontiere",
            "loading": "Chargement",
            "unpaid_company_stock": "Non paye : stock entreprise",
            "unpaid_in_transit": "Non paye : en cours",
            "unpaid_at_supplier": "Non paye : chez le fournisseur",
            "unpaid_costs": "Frais de trajets non vendus, non payes",
        },
    },
    "en": {
        "title": "Financial position",
        "export_date": "Export date",
        "assets": "What the company owns",
        "liabilities": "What the company owes",
        "total_assets": "Total owned by the company",
        "total_liabilities": "Total owed by the company",
        "net_result": "Net result",
        "net_help": "What the company owns - what it owes (shareholders and starting funds included). "
        "This is the net profit available for distribution.",
        "control": "Check: distributable net profit (Profit page)",
        "control_ok": "Matches the net result",
        "control_gap": "Gap with the net result",
        "note": "Debts are shown in full, as in the Working capital. Fuel and costs of a trip not yet sold "
        "and not yet paid appear on both sides (the asset financed by the debt): they cancel out in the "
        "net result.",
        "capital": "Capital contributed (information)",
        "lines": {
            "banks": "Banks",
            "cash": "Cash desks",
            "customer_receivables": "Customer receivables",
            "supplier_advances": "Advances paid to suppliers",
            "transporter_advances": "Advances paid to transporters",
            "associate_advances": "Advances to shareholders (not recovered)",
            "supplier_debts": "Supplier debts",
            "transporter_debts": "Transporter debts",
            "trip_fee_debts": "Customs / transit / fees debts",
            "customer_credit": "Advances received from customers",
            "shareholder_dues": "Owed to shareholders (capital and undrawn profit)",
            "unsold_fuel_paid": "Unsold fuel already paid",
            "unsold_costs_paid": "Trip costs paid on unsold fuel",
            "starting_funds": "Starting funds (opening balances and old debts)",
            "unsold_unpaid_covered": "Unsold fuel not yet paid (covered by debts)",
        },
        "children": {
            "company_stock": "Paid: company stock",
            "in_transit": "Paid: in transit",
            "at_supplier": "Paid: at the supplier",
            "customs": "Customs",
            "transit": "Transit",
            "road_transit": "Road transit",
            "border": "Border",
            "loading": "Loading",
            "unpaid_company_stock": "Unpaid: company stock",
            "unpaid_in_transit": "Unpaid: in transit",
            "unpaid_at_supplier": "Unpaid: at the supplier",
            "unpaid_costs": "Unsold, unpaid trip costs",
        },
    },
}
LABELS["ar"] = LABELS["fr"]

_BORDER = colors.HexColor("#d8d5cc")
_BAND = colors.HexColor("#f6f4ef")
_INK = colors.HexColor("#1d1b16")


def _side_table(*, title: str, side: dict, total_label: str, labels: dict, styles) -> Table:
    """One panel (assets or liabilities): title, each line with its non-zero
    sub-lines indented underneath, then the total on a dark band."""
    normal = ParagraphStyle("fpCell", parent=styles["Normal"], fontSize=9, leading=11)
    sub = ParagraphStyle("fpSub", parent=normal, fontSize=8, leading=10, leftIndent=8, textColor=colors.HexColor("#6b675c"))
    bold = ParagraphStyle("fpBold", parent=normal, fontName="Helvetica-Bold")
    total_style = ParagraphStyle("fpTotal", parent=bold, textColor=colors.white)
    rows = [[Paragraph(safe_text(title), ParagraphStyle("fpHead", parent=bold, fontSize=10)), ""]]
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for line in side["lines"]:
        rows.append([Paragraph(safe_text(labels["lines"][line["key"]]), normal), _format_money(line["amount"])])
        for child in line["children"]:
            if child["amount"] is None or float(child["amount"]) == 0:
                continue
            label = child.get("label") or labels["children"].get(child["key"], child["key"])
            rows.append([Paragraph(safe_text(label), sub), _format_money(child["amount"])])
    rows.append([Paragraph(safe_text(total_label), total_style), _format_money(side["total"])])
    last = len(rows) - 1
    commands += [
        ("BACKGROUND", (0, last), (-1, last), _INK),
        ("TEXTCOLOR", (1, last), (1, last), colors.white),
        ("FONTNAME", (1, last), (1, last), "Helvetica-Bold"),
    ]
    table = Table(rows, colWidths=[56 * mm, 28 * mm])
    table.setStyle(TableStyle(commands))
    return table


def render_financial_position_pdf(*, position: dict, lang: str = "fr") -> bytes:
    labels = LABELS.get(lang, LABELS["fr"])
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle("fpHeading", parent=styles["Heading2"])
    small = ParagraphStyle("fpSmall", parent=styles["Normal"], fontSize=8, leading=10)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm, title=labels["title"],
    )
    elements: list = masthead(
        company_name=DEFAULT_COMPANY_NAME, doc_title=labels["title"], styles=styles, heading_style=heading_style
    )
    elements.append(Paragraph(f"{labels['export_date']}: {datetime.date.today().isoformat()}", styles["Normal"]))
    elements.append(Spacer(1, 5 * mm))

    panels = Table(
        [[
            _side_table(
                title=labels["assets"], side=position["assets"], total_label=labels["total_assets"],
                labels=labels, styles=styles,
            ),
            _side_table(
                title=labels["liabilities"], side=position["liabilities"], total_label=labels["total_liabilities"],
                labels=labels, styles=styles,
            ),
        ]],
        colWidths=[90 * mm, 90 * mm],
    )
    panels.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    elements.append(panels)
    elements.append(Spacer(1, 5 * mm))

    gap_ok = float(position["gap"]) == 0
    result = Table(
        [
            [Paragraph(f"<b>{safe_text(labels['net_result'])}</b>", styles["Normal"]), _format_money(position["net_result"])],
            [Paragraph(safe_text(labels["net_help"]), small), ""],
            [labels["control"], _format_money(position["distributable_result"])],
            [labels["control_ok"] if gap_ok else f"{labels['control_gap']} : {_format_money(position['gap'])}", ""],
            [labels["capital"], _format_money(position["capital"])],
        ],
        colWidths=[125 * mm, 55 * mm],
    )
    result.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
        ("BACKGROUND", (0, 0), (-1, 1), _BAND),
        ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTSIZE", (1, 0), (1, 0), 12),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 3), (0, 3), colors.HexColor("#2f7d32" if gap_ok else "#b3261e")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(result)
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(safe_text(labels["note"]), small))
    doc.build(elements)
    return buffer.getvalue()
