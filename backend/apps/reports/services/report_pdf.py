# Shared PDF renderer for the Reports page (docs/superpowers/specs/2026-09-23-
# rapports-document-comptable-design.md, section report_pdf). Consumes the
# `document` payload built by report_document.build_report_document plus the
# raw rows, so the PDF prints exactly the structure and totals the Vue
# ReportSheet shows: masthead (logo, company, title), general-information
# grid, table(s) with repeated header, opening-balance row, summary block,
# "Page n / N" footer.

import datetime
import io
from decimal import Decimal

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
    "percent": 20, "number": 24,
}
_TEXT_MIN_MM = 30
_NUMERIC = ("money", "unit_money", "quantity", "percent", "number")
# One table row cannot span pages: a pasted multi-thousand-character note
# would make the whole export fail with a LayoutError. The PDF keeps the
# first MAX_TEXT_CHARS characters and ends with an ellipsis (the on-screen
# sheet always shows the full text).
MAX_TEXT_CHARS = 600


_CELL_PADDING = 6  # points: left + right padding of a table cell


def _p(text, style, lang, width=None) -> Paragraph:
    """Paragraph with escaped/shaped text; `width` (points) lets Arabic text
    wrap correctly inside a table cell."""
    return Paragraph(
        para_text(text, lang, bold=style.fontName.endswith("Bold"), width=width, size=style.fontSize), style
    )


def _cell_style(*, bold=False, numeric=False, size=8, color=INK, rtl=False) -> ParagraphStyle:
    return ParagraphStyle(
        f"cell-{int(bold)}-{int(numeric)}-{size}-{int(rtl)}",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=size * 1.45,
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


def _money(value, currency: str | None = None) -> str:
    """XOF (the default) is whole units; another document currency (a
    proforma or purchase order in EUR...) keeps its cents and its code."""
    if not currency or currency == "XOF":
        return _format_money(value).replace(" ", NBSP)
    whole, _, cents = f"{Decimal(str(value)):,.2f}".partition(".")
    return f"{whole.replace(',', NBSP)},{cents}{NBSP}{currency}"


def _cell_text(column: dict, value) -> str:
    """Display string of one cell (unescaped); DASH for an empty value."""
    if value is None or value == "":
        return DASH
    kind = column["kind"]
    if kind == "date":
        parsed = _as_date(value)
        return parsed.strftime("%d/%m/%Y") if parsed else str(value)
    if kind == "money":
        return _money(value, column.get("currency"))
    if kind == "unit_money":
        return _format_unit_money(value).replace(" ", NBSP)
    if kind == "quantity":
        return _format_quantity(value).replace(" ", NBSP)
    if kind == "number":  # unit-free, trailing zero decimals dropped (commercial documents)
        whole, _, decimals = f"{Decimal(str(value)):,.4f}".partition(".")
        decimals = decimals.rstrip("0")
        return whole.replace(",", NBSP) + (f",{decimals}" if decimals else "")
    if kind == "percent":
        return f"{Decimal(str(value)):.2f}".replace(".", ",") + NBSP + "%"
    if kind in ("enum", "status"):
        return column["enum_labels"].get(str(value), str(value))
    text = str(value)
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + "…"


def _summary_text(line: dict) -> str:
    value = line["value"]
    if line["kind"] == "money":
        return _money(value, line.get("currency"))
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
    company_par = _p(company, _cell_style(bold=True, size=15, rtl=rtl), document["lang"])
    tagline = document["company"].get("tagline")
    if tagline:  # document PDFs (spec 2026-10-11 documents-commerciaux)
        company_par = [company_par, _p(tagline, _cell_style(size=8, color=MUTED, rtl=rtl), document["lang"])]
    if logo is None:
        head = Table([[company_par]], colWidths=[available])
    elif rtl:
        head = Table([[company_par, logo]], colWidths=[available - 22 * mm, 22 * mm])
    else:
        head = Table([[logo, company_par]], colWidths=[22 * mm, available - 22 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    label_style = _cell_style(bold=True, size=8, color=MUTED, rtl=rtl)
    value_style = _cell_style(size=9, rtl=rtl)
    info = document["info"]
    label_w, value_w = 30 * mm, (available - 60 * mm) / 2
    rows = []
    for i in range(0, len(info), 2):
        cells = []
        for item in info[i : i + 2]:
            cells += [_p(item["label"], label_style, document["lang"]),
                      _p(item["value"], value_style, document["lang"], value_w - _CELL_PADDING)]
        while len(cells) < 4:
            cells.append("")
        rows.append(cells)
    widths = [label_w, value_w, label_w, value_w]
    if rtl:  # mirrored grid: value | label, and the pair order reversed
        rows = [list(reversed(row)) for row in rows]
        widths = list(reversed(widths))
    elements = [head, Spacer(1, 3 * mm), _p(title, _cell_style(bold=True, size=17, rtl=rtl), document["lang"]),
                Spacer(1, 3 * mm)]
    if rows:
        info_table = Table(rows, colWidths=widths, hAlign="RIGHT" if rtl else "LEFT")
        info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        elements.append(info_table)
    return elements + [
        Spacer(1, 2 * mm),
        HRFlowable(width="100%", thickness=0.8, color=INK, spaceAfter=4 * mm),
    ]


def _data_table(document: dict, table: dict, rows: list[dict], opening: dict | None, available: float, rtl: bool):
    lang = document["lang"]
    columns = list(reversed(table["columns"])) if rtl else table["columns"]
    widths = _column_widths(columns, available)
    header = [_p(c["label"], _cell_style(bold=True, numeric=c["align"] == "end", rtl=rtl), lang, w - _CELL_PADDING)
              for c, w in zip(columns, widths)]
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
        label = _p(opening["label"], _cell_style(bold=True, rtl=rtl), lang)
        value = _p(_cell_text({"kind": "money"}, opening["value"]), _cell_style(bold=True, numeric=True), lang)
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
        for column, column_width in zip(columns, widths):
            style = _cell_style(bold=bold, numeric=column["align"] == "end", rtl=rtl)
            cells.append(_p(_cell_text(column, row.get(column["field"])), style, lang, column_width - _CELL_PADDING))
        if bold:
            styles.append(("BACKGROUND", (0, len(data)), (-1, len(data)), TOTAL_FILL))
        data.append(cells)

    if not rows:
        empty = [_p(document["empty_text"], _cell_style(color=MUTED, rtl=rtl), lang)] + [""] * (len(columns) - 1)
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
        cells = [_p(line["label"], _cell_style(bold=bold, size=9, rtl=rtl), lang, 75 * mm - _CELL_PADDING),
                 _p(_summary_text(line), _cell_style(bold=bold, numeric=True, size=9), lang)]
        data.append(list(reversed(cells)) if rtl else cells)
        if bold:
            styles += [("BACKGROUND", (0, index), (-1, index), TOTAL_FILL), ("LINEABOVE", (0, index), (-1, index), 0.8, INK)]
    block = Table(data, colWidths=[45 * mm, 75 * mm] if rtl else [75 * mm, 45 * mm], hAlign="LEFT" if rtl else "RIGHT")
    block.setStyle(TableStyle(styles))
    return KeepTogether([Spacer(1, 6 * mm), block])


def _blocks(document: dict, available: float, rtl: bool) -> list:
    """Text blocks after the summary (amount in words, terms, notes) - the
    optional `blocks` key of the commercial documents."""
    lang, elements = document["lang"], []
    for block in document.get("blocks") or []:
        if not block.get("boxed"):
            # Plain paragraphs (not a table cell): long notes may flow over
            # several pages instead of raising a LayoutError.
            elements.append(Spacer(1, 4 * mm))
            if block.get("title"):
                elements.append(_p(block["title"], _cell_style(bold=True, size=9, rtl=rtl), lang, available))
            elements.append(_p(block["text"], _cell_style(size=9, rtl=rtl), lang, available))
            continue
        content = []
        if block.get("title"):
            content.append(_p(block["title"], _cell_style(bold=True, size=9, rtl=rtl), lang, available - 12))
        content.append(_p(block["text"], _cell_style(size=9, rtl=rtl), lang, available - 12))
        box = Table([[content]], colWidths=[available])
        style = [("LEFTPADDING", (0, 0), (-1, -1), 6 if block.get("boxed") else 0),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if block.get("boxed"):
            style += [("BOX", (0, 0), (-1, -1), 0.8, INK), ("BACKGROUND", (0, 0), (-1, -1), TOTAL_FILL)]
        box.setStyle(TableStyle(style))
        elements += [Spacer(1, 4 * mm), box]
    return elements


def _signatures(document: dict, available: float, rtl: bool) -> list:
    """One framed box per signer (optional `signatures` key)."""
    labels = list(document.get("signatures") or [])
    if not labels:
        return []
    if rtl:
        labels.reverse()
    gap = 10 * mm
    width = (available - gap * (len(labels) - 1)) / len(labels)
    cells, widths = [], []
    for index, label in enumerate(labels):
        if index:
            cells.append("")
            widths.append(gap)
        cells.append(_p(label, _cell_style(bold=True, size=9, rtl=rtl), document["lang"], width - 12))
        widths.append(width)
    table = Table([cells], colWidths=widths, rowHeights=[28 * mm])
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5)]
    style += [("BOX", (i, 0), (i, 0), 0.6, LINE) for i in range(0, len(cells), 2)]
    table.setStyle(TableStyle(style))
    return [KeepTogether([Spacer(1, 10 * mm), table])]


def _footer(document: dict, rtl: bool) -> list:
    """Company contact lines at the end of the document (`company.lines`)."""
    lines = document["company"].get("lines") or []
    if not lines:
        return []
    style = _cell_style(size=7, color=MUTED, rtl=rtl)
    style.alignment = 1  # centered
    elements = [Spacer(1, 8 * mm), HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=2 * mm)]
    elements += [_p(line, style, document["lang"]) for line in lines]
    return elements


def build_report_flowables(document: dict, rows: list[dict], lang: str | None = None):
    """(flowables, available width in points) for the document."""
    landscape_page = document["orientation"] == "landscape"
    page = landscape(A4) if landscape_page else A4
    available = page[0] - 2 * MARGIN
    rtl = document.get("direction") == "rtl"

    elements = _header_block(document, available, rtl)
    for index, table in enumerate(document["tables"]):
        if table.get("title"):
            elements.append(_p(table["title"], _cell_style(bold=True, size=10, rtl=rtl), document["lang"]))
            elements.append(Spacer(1, 1.5 * mm))
        opening = document["opening_balance"] if index == 0 else None
        # A table with a `section` shows only its own rows (spec §Changements du cadre).
        section = table.get("section")
        table_rows = [r for r in rows if r.get("section") == section] if section else rows
        elements.append(_data_table(document, table, table_rows, opening, available, rtl))
        elements.append(Spacer(1, 4 * mm))
    if document["summary"]:
        elements.append(_summary_block(document, available, rtl))
    elements += _blocks(document, available, rtl)
    elements += _signatures(document, available, rtl)
    elements += _footer(document, rtl)
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
