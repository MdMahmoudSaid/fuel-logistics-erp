# Report export tests (docs/PHASE_6_PLAN.md Etape 4: "Ajouter le support
# de l'exportation (CSV, Excel avec openpyxl)"). PDF export now lives in
# test_report_pdf.py.

import csv
import io
from decimal import Decimal

from openpyxl import load_workbook

from apps.reports.export import rows_to_csv, rows_to_xlsx

FIELDS = ["date", "reference", "amount"]
ROWS = [
    {"date": "2026-08-18", "reference": "SO-1", "amount": Decimal("600000.00")},
    {"date": "2026-08-19", "reference": "SO-2", "amount": None},
]


def test_rows_to_csv_writes_header_and_stringified_rows():
    content = rows_to_csv(FIELDS, ROWS)

    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    assert reader.fieldnames == FIELDS
    parsed = list(reader)
    assert parsed[0] == {"date": "2026-08-18", "reference": "SO-1", "amount": "600000.00"}
    assert parsed[1] == {"date": "2026-08-19", "reference": "SO-2", "amount": ""}


def test_rows_to_xlsx_writes_header_and_rows():
    content = rows_to_xlsx(FIELDS, ROWS)

    workbook = load_workbook(io.BytesIO(content))
    sheet = workbook.active
    values = list(sheet.values)
    assert values[0] == tuple(FIELDS)
    assert values[1] == ("2026-08-18", "SO-1", "600000.00")
    assert values[2] == ("2026-08-19", "SO-2", None)  # openpyxl reads back "" as None
