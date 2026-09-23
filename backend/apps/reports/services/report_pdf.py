# Shared PDF renderer for the Reports page (docs/superpowers/specs/2026-09-23-
# rapports-document-comptable-design.md, section report_pdf). Consumes the
# `document` payload built by report_document.build_report_document plus the
# raw rows, so the PDF prints exactly the structure and totals the Vue
# ReportSheet shows: masthead (logo, company, title), general-information
# grid, table(s) with repeated header, opening-balance row, summary block,
# "Page n / N" footer.

import datetime
import io

from django.utils import timezone
from django.utils.dateparse import parse_date
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.reports.services.ledger_pdf import _format_money, _format_quantity, _format_unit_money
from apps.reports.services.pdf_template import logo_image, numbered_canvas_cls, para_text

MARGIN = 12 * mm
INK = colors.HexColor("#12171c")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#c9ccd1")
HEADER_FILL = colors.HexColor("#e6edf5")
TOTAL_FILL = colors.HexColor("#f3f5f8")
NBSP = " "
DASH = "—"

# Fixed widths (mm) by column kind; text columns share what is left (>= 30mm).
_KIND_WIDTH_MM = {
    "date": 21, "ref": 32, "money": 26, "unit_money": 34, "quantity": 22, "enum": 30, "status": 30,
}
_TEXT_MIN_MM = 30
_NUMERIC = ("money", "unit_money", "quantity")


def _cell_style(*, bold=False, numeric=False, size=8, color=INK, rtl=False) -> ParagraphStyle:
    return ParagraphStyle(
        f"cell-{int(bold)}-{int(numeric)}-{size}-{int(rtl)}",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=size + 1.8,
        textColor=color,
        alignment=TA_RIGHT if (numeric or rtl) else TA_LEFT,
    )


def _as_date(value):
    if isinstance(value, datetime.datetime):
        return (timezone.localtime(value) if timezone.is_aware(value) else value).date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value:
        return parse_date(value[:10])
    return None


def _cell_text(column: dict, value) -> str:
    """Display string of one cell (unescaped); DASH for an empty value."""
    if value is None or value == "":
        return DASH
    kind = column["kind"]
    if kind == "date":
        parsed = _as_date(value)
        return parsed.strftime("%d/%m/%Y") if parsed else str(value)
    if kind == "money":
        return _format_money(value).replace(" ", NBSP)
    if kind == "unit_money":
        return _format_unit_money(value).replace(" ", NBSP)
    if kind == "quantity":
        return _format_quantity(value).replace(" ", NBSP)
    if kind in ("enum", "status"):
        return column["enum_labels"].get(str(value), str(value))
    return str(value)


def _summary_text(line: dict) -> str:
    value = line["value"]
    if line["kind"] == "money":
        return _format_money(value).replace(" ", NBSP)
    if line["kind"] == "quantity":
        return _format_quantity(value).replace(" ", NBSP)
    return str(value)


def _column_widths(columns: list[dict], available: float) -> list[float]:
    fixed = [_KIND_WIDTH_MM.get(c["kind"]) for c in columns]
    text_count = fixed.count(None)
    fixed_total = sum(w for w in fixed if w) * mm
    text_width = max((available - fixed_total) / text_count, _TEXT_MIN_MM * mm) if text_count else 0
    widths = [(w * mm if w else text_width) for w in fixed]
    total = sum(widths)
    # Too wide (even the minimums do not fit): scale down, never overflow.
    # Too narrow with no free-text column to absorb the slack: stretch to the
    # full width so the table lines up with the header block.
    if total > available or not text_count:
        widths = [w * available / total for w in widths]
    return widths


def _header_block(document: dict, available: float, rtl: bool) -> list:
    company, title = document["company"]["name"], document["title"]
    logo = logo_image(16 * mm)
    company_par = Paragraph(para_text(company, document["lang"]), _cell_style(bold=True, size=15, rtl=rtl))
    if logo is not None:
        head = Table([[logo, company_par]], colWidths=[22 * mm, available - 22 * mm])
    else:
        head = Table([[company_par]], colWidths=[available])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    label_style = _cell_style(bold=True, size=8, color=MUTED, rtl=rtl)
    value_style = _cell_style(size=9, rtl=rtl)
    info = document["info"]
    rows = []
    for i in range(0, len(info), 2):
        pair = info[i : i + 2]
        cells = []
        for item in pair:
            cells += [Paragraph(para_text(item["label"], document["lang"]), label_style),
                      Paragraph(para_text(item["value"], document["lang"]), value_style)]
        while len(cells) < 4:
            cells.append("")
        rows.append(cells)
    label_w, value_w = 30 * mm, (available - 60 * mm) / 2
    info_table = Table(rows, colWidths=[label_w, value_w, label_w, value_w], hAlign="LEFT")
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return [
        head,
        Spacer(1, 3 * mm),
        Paragraph(para_text(title, document["lang"]), _cell_style(bold=True, size=17, rtl=rtl)),
        Spacer(1, 3 * mm),
        info_table,
        Spacer(1, 2 * mm),
        HRFlowable(width="100%", thickness=0.8, color=INK, spaceAfter=4 * mm),
    ]


def _data_table(document: dict, table: dict, rows: list[dict], opening: dict | None, available: float, rtl: bool):
    lang = document["lang"]
    columns = table["columns"]
    widths = _column_widths(columns, available)
    header = [Paragraph(para_text(c["label"], lang), _cell_style(bold=True, numeric=c["align"] == "end", rtl=rtl))
              for c in columns]
    data = [header]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]

    if opening is not None:
        balance_index = next(i for i, c in enumerate(columns) if c["field"] == opening["column"])
        row = [""] * len(columns)
        label = Paragraph(para_text(opening["label"], lang), _cell_style(bold=True, rtl=rtl))
        value = Paragraph(
            para_text(_cell_text({"kind": "money"}, opening["value"]), lang), _cell_style(bold=True, numeric=True)
        )
        row[balance_index] = value
        if balance_index > 0:
            row[0] = label
            if balance_index > 1:
                styles.append(("SPAN", (0, len(data)), (balance_index - 1, len(data))))
        else:
            row[1] = label
            if len(columns) > 2:
                styles.append(("SPAN", (1, len(data)), (len(columns) - 1, len(data))))
        styles.append(("BACKGROUND", (0, len(data)), (-1, len(data)), TOTAL_FILL))
        data.append(row)

    emphasis = table.get("emphasis")
    for row in rows:
        bold = bool(emphasis and row.get(emphasis["field"]) == emphasis["equals"])
        cells = []
        for column in columns:
            text = para_text(_cell_text(column, row.get(column["field"])), lang)
            cells.append(Paragraph(f"<b>{text}</b>" if bold else text,
                                   _cell_style(numeric=column["align"] == "end", rtl=rtl)))
        if bold:
            styles.append(("BACKGROUND", (0, len(data)), (-1, len(data)), TOTAL_FILL))
        data.append(cells)

    if not rows:
        empty = [Paragraph(para_text(document["empty_text"], lang), _cell_style(color=MUTED))] + [""] * (len(columns) - 1)
        styles.append(("SPAN", (0, len(data)), (-1, len(data))))
        data.append(empty)

    result = Table(data, colWidths=widths, repeatRows=1)
    result.setStyle(TableStyle(styles))
    return result


def _summary_block(document: dict, available: float, rtl: bool):
    lang = document["lang"]
    data, styles = [], [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE)]
    for index, line in enumerate(document["summary"]):
        bold = line["emphasis"]
        data.append([
            Paragraph(para_text(line["label"], lang), _cell_style(bold=bold, size=9, rtl=rtl)),
            Paragraph(para_text(_summary_text(line), lang), _cell_style(bold=bold, numeric=True, size=9)),
        ])
        if bold:
            styles += [("BACKGROUND", (0, index), (-1, index), TOTAL_FILL), ("LINEABOVE", (0, index), (-1, index), 0.8, INK)]
    block = Table(data, colWidths=[75 * mm, 45 * mm], hAlign="RIGHT")
    block.setStyle(TableStyle(styles))
    return KeepTogether([Spacer(1, 6 * mm), block])


def build_report_flowables(document: dict, rows: list[dict], lang: str | None = None):
    """(flowables, available width in points) for the document."""
    landscape_page = document["orientation"] == "landscape"
    page = landscape(A4) if landscape_page else A4
    available = page[0] - 2 * MARGIN
    rtl = document.get("direction") == "rtl"

    elements = _header_block(document, available, rtl)
    for index, table in enumerate(document["tables"]):
        if table.get("title"):
            elements.append(Paragraph(para_text(table["title"], document["lang"]),
                                      _cell_style(bold=True, size=10, rtl=rtl)))
            elements.append(Spacer(1, 1.5 * mm))
        opening = document["opening_balance"] if index == 0 else None
        elements.append(_data_table(document, table, rows, opening, available, rtl))
        elements.append(Spacer(1, 4 * mm))
    elements.append(_summary_block(document, available, rtl))
    return elements, available


def render_report_pdf(document: dict, rows: list[dict], lang: str | None = None) -> bytes:
    """A4 PDF (portrait or landscape per document["orientation"])."""
    lang = lang or document["lang"]
    flowables, _ = build_report_flowables(document, rows, lang)
    page = landscape(A4) if document["orientation"] == "landscape" else A4
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=page, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 4 * mm,
        bottomMargin=MARGIN + 2 * mm, title=document["title"], author=document["company"]["name"],
    )
    doc.build(
        flowables,
        canvasmaker=numbered_canvas_cls(
            running_title=f"{document['company']['name']} — {document['title']}",
            page_label=document["labels"]["page"],
            lang=lang,
        ),
    )
    return buffer.getvalue()
