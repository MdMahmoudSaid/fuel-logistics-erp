# PDF of the "Situation financiere" page (client request 2026-10-17): what the
# company owns / owes / the net result. Same figures as the page
# (FinancialPositionService.get_position(), never recomputed here) and the same
# look as the Reports PDFs (report_pdf.py: logo + company masthead, title, rule,
# light-blue table header, grid lines, "Page n / N" footer), in fr / en / ar
# (Arabic is mirrored: the "owns" panel sits on the right).
#
# The two panels are ONE table (one row per line, the shorter side padded), so
# both always have the same height and the two totals sit on the same row.

import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import FOOTER_MARGIN, numbered_canvas_cls
from apps.reports.services.profit_pdf import _format_money
from apps.reports.services.report_pdf import (
    HEADER_FILL,
    INK,
    LINE,
    MARGIN,
    MUTED,
    TOTAL_FILL,
    _cell_style,
    _header_block,
    _p,
)

LABELS = {
    "fr": {
        "title": "Situation financière",
        "export_date": "Date d'export",
        "page": "Page {n} / {total}",
        "assets": "Ce que possède l'entreprise",
        "liabilities": "Ce que doit l'entreprise",
        "total": "Total",
        "net_result": "Résultat net",
        "control": "Bénéfice net à distribuer",
        "gap": "Écart avec le résultat net",
        "capital": "Capital apporté (information)",
        "starting_funds": "Fonds de départ (soldes d'ouverture et anciennes dettes)",
        "lines": {
            "banks": "Banques",
            "cash": "Caisses",
            "customer_receivables": "Créances clients",
            "supplier_advances": "Avances aux fournisseurs",
            "transporter_advances": "Avances aux transporteurs",
            "associate_advances": "Avances aux associés",
            "supplier_debts": "Dettes fournisseurs",
            "transporter_debts": "Dettes transporteurs",
            "trip_fee_debts": "Dettes douane / transit / frais",
            "customer_credit": "Avances reçues des clients",
            "shareholder_dues": "Dû aux associés",
            "unsold_fuel_paid": "Carburant non vendu payé",
            "unsold_costs_paid": "Frais payés sur carburant non vendu",
            "unsold_unpaid_covered": "Carburant non vendu non payé (couvert par les dettes)",
        },
        "children": {
            "company_stock": "Payé : stock entreprise",
            "in_transit": "Payé : en cours",
            "at_supplier": "Payé : chez le fournisseur",
            "customs": "Douane",
            "transit": "Transit",
            "road_transit": "Transit routière",
            "border": "Frontière",
            "loading": "Chargement",
            "unpaid_company_stock": "Non payé : stock entreprise",
            "unpaid_in_transit": "Non payé : en cours",
            "unpaid_at_supplier": "Non payé : chez le fournisseur",
            "unpaid_costs": "Frais de trajets non vendus",
        },
    },
    "en": {
        "title": "Financial position",
        "export_date": "Export date",
        "page": "Page {n} / {total}",
        "assets": "What the company owns",
        "liabilities": "What the company owes",
        "total": "Total",
        "net_result": "Net result",
        "control": "Distributable net profit",
        "gap": "Gap with the net result",
        "capital": "Capital contributed (information)",
        "starting_funds": "Starting funds (opening balances and old debts)",
        "lines": {
            "banks": "Banks",
            "cash": "Cash desks",
            "customer_receivables": "Customer receivables",
            "supplier_advances": "Advances to suppliers",
            "transporter_advances": "Advances to transporters",
            "associate_advances": "Advances to shareholders",
            "supplier_debts": "Supplier debts",
            "transporter_debts": "Transporter debts",
            "trip_fee_debts": "Customs / transit / fees debts",
            "customer_credit": "Advances from customers",
            "shareholder_dues": "Owed to shareholders",
            "unsold_fuel_paid": "Unsold fuel paid",
            "unsold_costs_paid": "Costs paid on unsold fuel",
            "unsold_unpaid_covered": "Unsold fuel not paid (covered by debts)",
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
            "unpaid_costs": "Unsold trip costs",
        },
    },
    "ar": {
        "title": "الوضعية المالية",
        "export_date": "تاريخ التصدير",
        "page": "صفحة {n} / {total}",
        "assets": "ما للمؤسسة",
        "liabilities": "ما على المؤسسة",
        "total": "المجموع",
        "net_result": "النتيجة الصافية",
        "control": "الربح الصافي القابل للتوزيع",
        "gap": "فرق مع النتيجة الصافية",
        "capital": "رأس المال المساهم به (للمعلومة)",
        "starting_funds": "أموال البداية (الأرصدة الافتتاحية والديون القديمة)",
        "lines": {
            "banks": "البنوك",
            "cash": "الصناديق",
            "customer_receivables": "مستحقات العملاء",
            "supplier_advances": "دفعات مقدّمة للموردين",
            "transporter_advances": "دفعات مقدّمة للناقلين",
            "associate_advances": "سلفات للشركاء",
            "supplier_debts": "ديون الموردين",
            "transporter_debts": "ديون الناقلين",
            "trip_fee_debts": "ديون الجمارك / العبور / الرسوم",
            "customer_credit": "دفعات مقدّمة من العملاء",
            "shareholder_dues": "مستحقات الشركاء",
            "unsold_fuel_paid": "وقود غير مباع مدفوع",
            "unsold_costs_paid": "رسوم مدفوعة على وقود غير مباع",
            "unsold_unpaid_covered": "وقود غير مباع غير مدفوع (مغطّى بالديون)",
        },
        "children": {
            "company_stock": "مدفوع: مخزون الشركة",
            "in_transit": "مدفوع: قيد النقل",
            "at_supplier": "مدفوع: لدى المورد",
            "customs": "الجمارك",
            "transit": "العبور",
            "road_transit": "العبور البري",
            "border": "الحدود",
            "loading": "التحميل",
            "unpaid_company_stock": "غير مدفوع: مخزون الشركة",
            "unpaid_in_transit": "غير مدفوع: قيد النقل",
            "unpaid_at_supplier": "غير مدفوع: لدى المورد",
            "unpaid_costs": "رسوم رحلات غير مباعة",
        },
    },
}

RED = colors.HexColor("#b3261e")

# Column widths (mm) of one panel: label | amount; the gap sits between panels.
_LABEL_W, _AMOUNT_W, _GAP_W = 60, 30, 6


def _entries(side: dict, labels: dict) -> list[tuple[str, str, bool]]:
    """(text, formatted amount, is_sub_line) for every line and non-zero
    sub-line of one side, in page order."""
    entries = []
    for line in side["lines"]:
        entries.append((labels["lines"][line["key"]], _money(line["amount"]), False))
        for child in line["children"]:
            if child["amount"] is None or float(child["amount"]) == 0:
                continue
            text = child.get("label") or labels["children"].get(child["key"], child["key"])
            entries.append((text, _money(child["amount"]), True))
    return entries


NBSP = "\u00a0"


def _money(value) -> str:
    return _format_money(value).replace(" ", NBSP)


def _label_cell(text, sub, lang, rtl, width):
    if not text:
        return ""
    style = _cell_style(size=8 if sub else 9, color=MUTED if sub else INK, rtl=rtl)
    if sub:  # sub-lines are indented under their line, towards the reading direction
        style.rightIndent, style.leftIndent = (6, 0) if rtl else (0, 6)
    return _p(text, style, lang, width - 8 - 6)


def _amount_cell(amount, sub, bold=False):
    if not amount:
        return ""
    return Paragraph(amount, _cell_style(numeric=True, bold=bold, size=8 if sub else 9, color=MUTED if sub else INK))


def _panels_table(position: dict, labels: dict, lang: str, rtl: bool):
    left = _entries(position["assets"], labels)
    right = _entries(position["liabilities"], labels)
    height = max(len(left), len(right))
    left += [("", "", False)] * (height - len(left))
    right += [("", "", False)] * (height - len(right))

    label_w, amount_w, gap_w = _LABEL_W * mm, _AMOUNT_W * mm, _GAP_W * mm
    head_style = _cell_style(bold=True, size=9, rtl=rtl)
    total_style = _cell_style(bold=True, size=9, rtl=rtl)

    def row(a_label, a_amount, b_label, b_amount):
        cells = [a_label, a_amount, "", b_label, b_amount]
        return list(reversed(cells)) if rtl else cells

    head = [_p(labels["assets"], head_style, lang), "", "", _p(labels["liabilities"], head_style, lang), ""]
    # Panel order is mirrored in Arabic; each title sits in its panel's first (spanned) cell.
    rows = [[head[3], "", "", head[0], ""] if rtl else head]
    for (a_text, a_amount, a_sub), (b_text, b_amount, b_sub) in zip(left, right):
        rows.append(
            row(
                _label_cell(a_text, a_sub, lang, rtl, label_w), _amount_cell(a_amount, a_sub),
                _label_cell(b_text, b_sub, lang, rtl, label_w), _amount_cell(b_amount, b_sub),
            )
        )
    rows.append(
        row(
            _p(labels["total"], total_style, lang),
            _amount_cell(_money(position["assets"]["total"]), False, bold=True),
            _p(labels["total"], total_style, lang),
            _amount_cell(_money(position["liabilities"]["total"]), False, bold=True),
        )
    )

    # Columns: 0-1 first panel, 2 gap, 3-4 second panel (rows are reversed for
    # Arabic, so the "owns" panel ends up on the right).
    widths = [label_w, amount_w, gap_w, label_w, amount_w]
    if rtl:
        widths.reverse()
    last = len(rows) - 1
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for start, end in ((0, 1), (3, 4)):
        style += [
            ("BOX", (start, 0), (end, last), 0.4, LINE),
            ("BACKGROUND", (start, 0), (end, 0), HEADER_FILL),
            ("SPAN", (start, 0), (end, 0)),
            ("BACKGROUND", (start, last), (end, last), TOTAL_FILL),
            ("LINEABOVE", (start, last), (end, last), 0.8, INK),
        ]
    # Thin separators only under rows that carry something (padding stays blank).
    first_amounts = [a for _, a, _ in left]
    second_amounts = [b for _, b, _ in right]
    first_cols, second_cols = ((3, 4), (0, 1)) if rtl else ((0, 1), (3, 4))
    for index in range(height):
        for (start, end), amount in ((first_cols, first_amounts[index]), (second_cols, second_amounts[index])):
            if amount:
                style.append(("LINEBELOW", (start, index + 1), (end, index + 1), 0.3, LINE))
    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle(style))
    return table


def _result_block(position: dict, labels: dict, lang: str, rtl: bool):
    """Net result (bold band), the distributable profit it must equal and the
    capital; plus a red gap line only when the two ever differ."""
    rows = [
        (labels["net_result"], position["net_result"], True, INK),
        (labels["control"], position["distributable_result"], False, INK),
    ]
    if float(position["gap"]) != 0:
        rows.append((labels["gap"], position["gap"], True, RED))
    rows.append((labels["capital"], position["capital"], False, MUTED))

    data = []
    for index, (label, value, bold, color) in enumerate(rows):
        size = 10 if index == 0 else 9
        cells = [
            _p(label, _cell_style(bold=bold, size=size, color=color, rtl=rtl), lang, 75 * mm - 6),
            Paragraph(_money(value), _cell_style(bold=bold, numeric=True, size=size, color=color)),
        ]
        data.append(list(reversed(cells)) if rtl else cells)
    block = Table(data, colWidths=[45 * mm, 75 * mm] if rtl else [75 * mm, 45 * mm], hAlign="LEFT" if rtl else "RIGHT")
    block.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                ("BACKGROUND", (0, 0), (-1, 0), TOTAL_FILL),
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, INK),
            ]
        )
    )
    return block


def render_financial_position_pdf(*, position: dict, lang: str = "fr") -> bytes:
    lang = lang if lang in LABELS else "fr"
    labels = LABELS[lang]
    rtl = lang == "ar"
    available = A4[0] - 2 * MARGIN
    document = {
        "lang": lang,
        "title": labels["title"],
        "company": {"name": "AZUR ÉNERGIE"},
        "info": [{"label": labels["export_date"], "value": datetime.date.today().strftime("%d/%m/%Y")}],
    }
    elements = _header_block(document, available, rtl)
    elements.append(_panels_table(position, labels, lang, rtl))
    elements.append(Spacer(1, 8 * mm))
    elements.append(_result_block(position, labels, lang, rtl))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 4 * mm,
        bottomMargin=FOOTER_MARGIN, title=labels["title"], author="AZUR ÉNERGIE",
    )
    doc.build(
        elements,
        canvasmaker=numbered_canvas_cls(
            running_title=f"AZUR ÉNERGIE — {labels['title']}", page_label=labels["page"], lang=lang
        ),
    )
    return buffer.getvalue()
