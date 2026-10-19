# PDF export for the "Benefices" page (client request 2026-09-06) - a real
# structured document (reportlab), never a screenshot of the page: the
# profitability figures, the full fond-de-roulement breakdown (including
# the douane/transit/transit routiere/autres frais lines the page itself
# only shows as one merged "dettes ouvertes" figure), and the per-trip
# margin detail table. Deliberately its own module, mirroring ledger_pdf.py/
# quotation_pdf.py's self-contained pattern rather than sharing their
# private helpers - every value handed to Paragraph is escaped via
# _safe_paragraph_text (security fix 2026-09-06, apps.reports.services.
# ledger_pdf docstring), even though nothing here is currently free text
# typed by an operator (trip references/client names go through Table
# cells only, never markup-parsed by reportlab).

import datetime
import io
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import (
    DEFAULT_COMPANY_NAME,
    FOOTER_MARGIN,
    masthead,
    numbered_canvas_cls,
    safe_text,
)


ZERO = Decimal("0.00")

PROFIT_PDF_LABELS = {
    "fr": {
        "title": "Rapport de benefices",
        "period": "Periode",
        "period_all_time": "Depuis le debut",
        "export_date": "Date d'export",
        "profitability": "Rentabilite",
        "operationalProfit": "Benefice operationnel des trajets",
        "revenue": "Chiffre d'affaires",
        "tripsCount": "Trajets pris en compte",
        "adjustment": "ajustement",
        "generalExpenses": "Depenses generales payees",
        "netProfit": "Benefice net apres depenses generales",
        "workingCapital": "Fond de roulement - detail complet",
        "treasuryAvailable": "Tresorerie disponible",
        "customerReceivables": "Creances clients",
        "gross": "= Brut (tresorerie + creances)",
        "shareholderDues": "Dues aux associes (information)",
        "supplierDebt": "- Dette fournisseurs",
        "transporterDebt": "- Dette transporteurs",
        "customsDebt": "- Douane",
        "transitDebt": "- Transit",
        "roadTransitDebt": "- Transit routiere",
        "otherDebt": "- Autres frais (frontiere / chargement)",
        "advancesPaid": "+ Avances versees (fournisseurs, transporteurs, associes)",
        "unsoldCosts": "+ Frais de trajet engages (carburant non vendu)",
        "totalDebts": "= Total des dettes ouvertes (a deduire)",
        "supplierReliquat": "+ Stock : chez le fournisseur",
        "supplierInTransit": "+ Stock : en cours",
        "supplierCompanyStock": "+ Stock : stock entreprise",
        "totalWorkingCapital": "= Fond de roulement total",
        "capital": "Capital apporte",
        "alreadyDistributed": "Deja reparti (non retire)",
        "distributableResult": "= Benefice a distribuer",
        "tripDetail": "Detail des couts par trajet",
        "table": {
            "trip_reference": "Reference",
            "client": "Client",
            "product": "Produit",
            "quantity_loaded": "Qte chargee",
            "quantity_invoiced": "Qte facturee",
            "transporter_loss_quantity": "Perte",
            "transporter_loss_indemnity": "Indemnisation",
            "supplier_unit_price": "Prix fourn./L",
            "real_total_cost": "Cout total",
            "unit_selling_price": "Prix vente/L",
            "unit_profit": "Benefice/L",
            "current_margin": "Benefice total",
        },
    },
    "en": {
        "title": "Profit report",
        "period": "Period",
        "period_all_time": "Since the beginning",
        "export_date": "Export date",
        "profitability": "Profitability",
        "operationalProfit": "Operational profit (trips)",
        "revenue": "Revenue",
        "tripsCount": "Trips counted",
        "adjustment": "adjustment",
        "generalExpenses": "General expenses paid",
        "netProfit": "Net profit after general expenses",
        "workingCapital": "Working capital - full breakdown",
        "treasuryAvailable": "Available treasury",
        "customerReceivables": "Customer receivables",
        "gross": "= Gross (treasury + receivables)",
        "shareholderDues": "Owed to shareholders (information)",
        "supplierDebt": "- Supplier debt",
        "transporterDebt": "- Transporter debt",
        "customsDebt": "- Customs",
        "transitDebt": "- Transit",
        "roadTransitDebt": "Road transit",
        "otherDebt": "Other fees (border / loading / misc.)",
        "advancesPaid": "+ Advances paid (suppliers, transporters, associates)",
        "unsoldCosts": "+ Trip costs engaged (unsold fuel)",
        "totalDebts": "= Total open debts (deducted)",
        "supplierReliquat": "+ Stock: at the supplier",
        "supplierInTransit": "+ Stock: in transit",
        "supplierCompanyStock": "+ Stock: company stock",
        "totalWorkingCapital": "= Total working capital",
        "capital": "Capital contributed",
        "alreadyDistributed": "Already distributed (not withdrawn)",
        "distributableResult": "= Profit left to distribute",
        "tripDetail": "Trip cost detail",
        "table": {
            "trip_reference": "Reference",
            "client": "Customer",
            "product": "Product",
            "quantity_loaded": "Qty loaded",
            "quantity_invoiced": "Qty invoiced",
            "transporter_loss_quantity": "Loss",
            "transporter_loss_indemnity": "Indemnity",
            "supplier_unit_price": "Supplier/L",
            "real_total_cost": "Total cost",
            "unit_selling_price": "Selling/L",
            "unit_profit": "Profit/L",
            "current_margin": "Total profit",
        },
    },
}
# AR: labels intentionally kept in French, same documented policy as
# ledger_pdf.py/quotation_pdf.py (no embedded Arabic-capable font/shaping
# installed in this pass).
PROFIT_PDF_LABELS["ar"] = PROFIT_PDF_LABELS["fr"]

_SUMMARY_TABLE_STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]
)

def _bold_row(row_index: int):
    """A TableStyle command bolding one full row (both label and value
    columns) of a 2-column label/value summary table."""
    return ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold")

_DETAIL_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12171c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f4ef")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        # Bug fix (found in visual review, 2026-09-06): reportlab's default
        # cell padding is 6pt each side (~4.2mm total per column) - fine
        # for the wide 2-column summary tables above, but on this dense
        # 12-column table it was eating enough width that a header visibly
        # ran into its neighbour once the per-litre columns grew from 2 to
        # 4 decimals. "Perte transp." (the narrowest column's header) was
        # shortened to "Perte" for the same reason - the table's own title
        # already says these are per-trip costs, so the abbreviation loses
        # no information.
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
    ]
)


_safe_paragraph_text = safe_text


def _format_money(value) -> str:
    """`4 874 000 XOF` - rounded to the nearest unit, space-grouped, same
    convention as the frontend's formatMoney() (utils/currency.ts) so the
    PDF's figures read identically to the screen they came from."""
    if value is None:
        return ""
    amount = int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{amount:,}".replace(",", " ") + " XOF"


def _format_quantity(value) -> str:
    """`45 000 L` - same rounding/grouping convention as formatQuantity()."""
    if value is None:
        return ""
    amount = int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{amount:,}".replace(",", " ") + " L"


def _format_unit_money(value) -> str:
    """`500,0000 XOF/L` - 4 decimals, French decimal comma, matching the
    frontend's formatUnitMoney() (utils/currency.ts). Client request
    (2026-09-06): 2 decimals hid enough precision that summing displayed
    per-litre prices back up visibly didn't reconstruct the real total (a
    30 000 XOF / 45 000 L fee showed as "0,67 XOF/L", and 0,67 x 45 000 =
    30 150, not 30 000) - 4 decimals matches the backend's own internal
    per-litre precision (apps/trips/services.py `_UNIT = Decimal("0.0001")`)."""
    if value is None:
        return ""
    quantized = Decimal(value).quantize(Decimal("0.0001"))
    formatted = f"{quantized:,.4f}"
    integer_part, _, decimal_part = formatted.partition(".")
    return f"{integer_part.replace(',', ' ')},{decimal_part} XOF/L"


def _labels(lang: str) -> dict:
    return PROFIT_PDF_LABELS.get(lang, PROFIT_PDF_LABELS["fr"])


def _doc_template(buffer, *, title: str) -> SimpleDocTemplate:
    # Landscape, not portrait (unlike every other PDF in this app): the
    # trip-detail table below has 12 columns of real financial data (the
    # client explicitly asked for the full table, not a trimmed one) and
    # overflowed off the right edge of a portrait A4 page in review -
    # landscape's ~267mm usable width (vs ~180mm portrait) is what actually
    # fits it without truncating a column or shrinking the font past
    # legibility.
    return SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=FOOTER_MARGIN,
        title=title,
    )


def render_profit_report_pdf(
    *,
    preview: dict,
    other_debts_breakdown: dict,
    rows: list[dict],
    lang: str = "fr",
) -> bytes:
    """Full "Benefices" page export: profitability, the complete fond-de-
    roulement breakdown, and the per-trip margin detail table - all values
    read from `preview` (ShareholderProfitPreviewService.get_preview()),
    `other_debts_breakdown` (WorkingCapitalService.get_other_debts_breakdown())
    and `rows` (MarginReportQuery.run()), never recomputed here (same rule
    every other PDF/report in this app follows).

    The period shown is `preview["period_start"]`/`period_end"]` - what the
    backend actually computed the figures over - not the raw request
    params, since get_preview() can silently widen an unset date_from to
    "since the last validated distribution".
    """
    labels = _labels(lang)
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle("headingCustom", parent=styles["Heading2"])
    # Bug fix (found in visual review, 2026-09-06): the detail table's
    # "client" column is free text of unbounded length (a customer's real
    # name/company, e.g. "Etablissements Diallo & Freres SARL") - as a
    # plain string it doesn't wrap and visibly overflows into the next
    # column instead. Wrapped in a small Paragraph so it word-wraps within
    # its own column width like every other cell. Free text reaching a
    # Paragraph must be escaped (_safe_paragraph_text) - see that
    # function's docstring.
    cell_style = ParagraphStyle("detailCell", parent=styles["Normal"], fontSize=7, leading=8)

    buffer = io.BytesIO()
    doc = _doc_template(buffer, title=labels["title"])

    elements: list = masthead(
        company_name=DEFAULT_COMPANY_NAME, doc_title=labels["title"], styles=styles, heading_style=heading_style
    )

    period_start = preview.get("period_start")
    period_end = preview.get("period_end")
    if period_start or period_end:
        period_text = f"{period_start or '...'} → {period_end or '...'}"
    else:
        period_text = labels["period_all_time"]
    elements.append(Paragraph(f"{labels['period']}: {period_text}", styles["Normal"]))
    elements.append(
        Paragraph(
            f"{labels['export_date']}: {datetime.date.today().isoformat()}", styles["Normal"]
        )
    )
    elements.append(Spacer(1, 8 * mm))

    # Section 1: Rentabilite.
    # Rows carry their own revenue: a quantity x price product would be
    # wrong on a since-closure adjustment row (spec 2026-10-05).
    revenue = preview["revenue"]
    elements.append(Paragraph(_safe_paragraph_text(labels["profitability"]), heading_style))
    elements.append(Spacer(1, 2 * mm))
    profitability_rows = [
        (labels["operationalProfit"], _format_money(preview["operational_profit"])),
        (labels["revenue"], _format_money(revenue)),
        (labels["tripsCount"], str(len(rows))),
        (labels["generalExpenses"], _format_money(preview["general_expenses_paid"])),
        (labels["netProfit"], _format_money(preview["net_profit"])),
    ]
    profitability_table = Table(profitability_rows, colWidths=[110 * mm, 60 * mm])
    profitability_table.setStyle(_SUMMARY_TABLE_STYLE)
    profitability_table.setStyle(TableStyle([_bold_row(4)]))
    elements.append(profitability_table)
    elements.append(Spacer(1, 8 * mm))

    # Section 2: Fond de roulement - full breakdown (client's own explicit
    # request: never fold douane/transit/transit routiere/autres frais
    # into one merged figure).
    wc = preview["working_capital"]
    elements.append(Paragraph(_safe_paragraph_text(labels["workingCapital"]), heading_style))
    elements.append(Spacer(1, 2 * mm))
    wc_rows = [
        (labels["treasuryAvailable"], _format_money(wc["treasury_available"])),
        (labels["customerReceivables"], _format_money(wc["customer_receivables"])),
        (labels["gross"], _format_money(wc["gross"])),
        (labels["supplierCompanyStock"], _format_money(wc["supplier_company_stock_value"])),
        (labels["supplierInTransit"], _format_money(wc["supplier_in_transit_value"])),
        (labels["supplierReliquat"], _format_money(wc["supplier_reliquat_value"])),
        (labels["advancesPaid"], _format_money(wc["advances_paid"])),
        (labels["unsoldCosts"], _format_money(wc["unsold_costs"])),
        (labels["supplierDebt"], _format_money(-wc["supplier_debt_total"])),
        (labels["transporterDebt"], _format_money(-wc["transporter_debt_total"])),
        (labels["customsDebt"], _format_money(-other_debts_breakdown["customs"])),
        (labels["transitDebt"], _format_money(-other_debts_breakdown["transit"])),
        (labels["roadTransitDebt"], _format_money(-other_debts_breakdown["road_transit"])),
        (labels["otherDebt"], _format_money(-other_debts_breakdown["other"])),
        (
            labels["totalDebts"],
            _format_money(
                -(wc["supplier_debt_total"] + wc["transporter_debt_total"] + wc["other_debts"])
            ),
        ),
        (labels["totalWorkingCapital"], _format_money(wc["total"])),
        (labels["capital"], _format_money(wc["capital"])),
        (labels["shareholderDues"], _format_money(wc["shareholder_dues"])),
        (labels["alreadyDistributed"], _format_money(preview["already_distributed"])),
        (labels["distributableResult"], _format_money(preview["distributable_result"])),
    ]
    wc_table = Table(wc_rows, colWidths=[110 * mm, 60 * mm])
    wc_table.setStyle(_SUMMARY_TABLE_STYLE)
    wc_table.setStyle(TableStyle([_bold_row(idx) for idx in (2, 14, 15, 19)]))
    elements.append(wc_table)
    elements.append(Spacer(1, 8 * mm))

    # Section 3: per-trip detail - included at the client's own request
    # (2026-09-06), same 12 columns as the page's own table.
    if rows:
        table_labels = labels["table"]
        fields = list(table_labels.keys())
        text_fields = {"trip_reference", "client", "product"}
        header_left = ParagraphStyle(
            "detailHeaderLeft", parent=styles["Normal"], fontName="Helvetica-Bold",
            fontSize=7, leading=8, textColor=colors.white,
        )
        header_right = ParagraphStyle("detailHeaderRight", parent=header_left, alignment=TA_RIGHT)
        header = [
            Paragraph(
                _safe_paragraph_text(table_labels[f]),
                header_left if f in text_fields else header_right,
            )
            for f in fields
        ]
        formatters = {
            "quantity_loaded": _format_quantity,
            "quantity_invoiced": _format_quantity,
            "transporter_loss_quantity": _format_quantity,
            "transporter_loss_indemnity": _format_money,
            "supplier_unit_price": _format_unit_money,
            "real_total_cost": _format_money,
            "unit_selling_price": _format_unit_money,
            "unit_profit": _format_unit_money,
            "current_margin": _format_money,
        }
        # On a since-closure adjustment row only the additive columns are
        # deltas; a unit price/profit there would be misleading.
        unit_fields = {"supplier_unit_price", "unit_selling_price", "unit_profit"}

        def _cell(field, row):
            if row.get("is_adjustment") and field in unit_fields:
                return "—"
            if field == "trip_reference" and row.get("is_adjustment"):
                return Paragraph(
                    _safe_paragraph_text(f"{row.get(field, '')} ({labels['adjustment']})"),
                    cell_style,
                )
            if field in formatters:
                return formatters[field](row.get(field))
            if field in ("client", "trip_reference"):
                return Paragraph(_safe_paragraph_text(row.get(field, "")), cell_style)
            return str(row.get(field, ""))

        detail_data = [header] + [[_cell(field, row) for field in fields] for row in rows]
        elements.append(Paragraph(_safe_paragraph_text(labels["tripDetail"]), heading_style))
        elements.append(Spacer(1, 2 * mm))
        # Explicit widths summing to 264mm - the ~267mm usable width of the
        # landscape page, so the table fills it edge to edge instead of
        # floating narrower and centred (2026-09-25: "Reference" at the old
        # 18mm was narrower than "TRIP-04-04-000001" at 7pt and ran into the
        # Client column). The numeric columns hold at most "1 000,0000 XOF/L"
        # / "31 500 000 XOF" (~21mm at 7pt), so 24mm leaves breathing room.
        detail_col_widths = [
            28 * mm, 30 * mm, 16 * mm, 18 * mm, 18 * mm, 14 * mm,
            20 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm,
        ]
        detail_table = Table(detail_data, repeatRows=1, colWidths=detail_col_widths, hAlign="LEFT")
        detail_table.setStyle(_DETAIL_TABLE_STYLE)
        elements.append(detail_table)

    doc.build(elements, canvasmaker=numbered_canvas_cls(running_title=f"{DEFAULT_COMPANY_NAME} — {labels['title']}", lang=lang, side_margin=15 * mm))
    return buffer.getvalue()
