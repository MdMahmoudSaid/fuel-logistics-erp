# Shared CSV/Excel export for report query rows (docs/PHASE_6_PLAN.md Etape 4).
# The Reports page PDF is rendered by services/report_pdf.py.
#
# Every value is rendered as text (Decimal kept as its exact string form
# rather than converted to a binary float) so financial figures never pick
# up floating-point rounding noise in the exported file.

import csv
import datetime
import io
from decimal import Decimal

from openpyxl import Workbook


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
