# Shared CSV/Excel/PDF export for report query rows (docs/PHASE_6_PLAN.md
# Etape 4; PDF added for the "Exporter PDF" action on the Reports page).
#
# Every value is rendered as text (Decimal kept as its exact string form
# rather than converted to a binary float) so financial figures never pick
# up floating-point rounding noise in the exported file.

import csv
import datetime
import io
from decimal import Decimal

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def rows_to_csv(fields: list[str], rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _stringify(row.get(field)) for field in fields})
    return buffer.getvalue().encode("utf-8-sig")


def rows_to_xlsx(fields: list[str], rows: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(fields)
    for row in rows:
        sheet.append([_stringify(row.get(field)) for field in fields])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rows_to_pdf(fields: list[str], rows: list[dict], title: str = "") -> bytes:
    """Simple tabular PDF for the Reports page "Exporter PDF" action -
    same field/row shape as rows_to_csv/rows_to_xlsx, just rendered as a
    reportlab Table instead of a spreadsheet/CSV. Landscape A4 since report
    tables commonly run wide (statements alone have 6 columns)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=title,
    )
    header = [field.replace("_", " ").title() for field in fields]
    data = [header] + [[_stringify(row.get(field)) for field in fields] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12171c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f4ef")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    doc.build([table])
    return buffer.getvalue()
