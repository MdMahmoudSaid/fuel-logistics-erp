# PDF export for the 3 party ledgers (Grand livre fournisseur/transporteur/
# client) and for a single trip's transport settlement ("Reglement par
# trajet") - docs/superpowers/specs/2026-09-04-recette-corrections-design.md
# Section 5. No business calculation lives here: this module only prints
# dicts/model instances already produced elsewhere
# (SupplierLedgerService.get_ledger / TransporterLedgerService.get_ledger,
# the CustomerViewSet.ledger response, and TransportPayment). Same
# reportlab dependency already used by apps/reports/export.py
# (rows_to_pdf) - no new dependency added.
#
# KNOWN LIMITATION - Arabic (lang="ar"), documented per the client's
# explicit pre-approval of a minimal correction over a blocking one:
# reportlab's built-in Helvetica font has no Arabic glyphs, and reportlab
# does not do bidi reordering or Arabic letter-shape joining on its own.
# Rendering real Arabic text would need an embedded Unicode font (e.g.
# Noto Naskh Arabic) plus the `arabic-reshaper` and `python-bidi` packages
# to reshape/reorder the text before layout - none of that is installed,
# and adding new dependencies is out of scope for this "small, safe
# correction" pass. For lang="ar" this module therefore only applies a
# minimal RTL approximation (right-aligned paragraphs, table columns
# reversed) while keeping the FRENCH field labels as a documented
# fallback, rather than emitting unreadable tofu glyphs. A follow-up
# ticket should add proper Arabic shaping/fonts if the client needs true
# Arabic PDFs.

import datetime
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# No per-tenant "company name" setting exists anywhere in this codebase
# (grepped models/settings/frontend branding) - a fixed constant is used
# for the PDF header, matching the generic branding already used
# elsewhere (frontend/index.html <title>).
DEFAULT_COMPANY_NAME = "Fuel Logistics ERP"

LEDGER_PDF_LABELS = {
    "fr": {
        "title": "Grand livre",
        "account_type": "Type de compte",
        "party": "Compte",
        "export_date": "Date d'export",
        "summary": "Resume des soldes",
        "history": "Historique des operations",
        "settlement_title": "Reglement par trajet",
        "trip_reference": "Reference du trajet",
        "truck": "Camion",
        "plate": "Plaque (tracteur / citerne)",
        "transporter": "Transporteur",
        "client": "Client",
        "product": "Produit",
        "quantity": "Quantite chargee",
        "trip_status": "Statut du trajet",
        "gross_amount": "Montant brut",
        "deductions": "Deductions",
        "net_amount": "Montant net",
        "date": "Date",
        "notes": "Notes",
    },
    "en": {
        "title": "Ledger",
        "account_type": "Account type",
        "party": "Account",
        "export_date": "Export date",
        "summary": "Balance summary",
        "history": "Operation history",
        "settlement_title": "Trip settlement",
        "trip_reference": "Trip reference",
        "truck": "Truck",
        "plate": "Plate (tractor / tanker)",
        "transporter": "Transporter",
        "client": "Client",
        "product": "Product",
        "quantity": "Quantity loaded",
        "trip_status": "Trip status",
        "gross_amount": "Gross amount",
        "deductions": "Deductions",
        "net_amount": "Net amount",
        "date": "Date",
        "notes": "Notes",
    },
    # AR: labels intentionally kept in French pending an embedded
    # Arabic-capable font + reshaping/bidi support - see module docstring.
    "ar": {
        "title": "Grand livre",
        "account_type": "Type de compte",
        "party": "Compte",
        "export_date": "Date d'export",
        "summary": "Resume des soldes",
        "history": "Historique des operations",
        "settlement_title": "Reglement par trajet",
        "trip_reference": "Reference du trajet",
        "truck": "Camion",
        "plate": "Plaque (tracteur / citerne)",
        "transporter": "Transporteur",
        "client": "Client",
        "product": "Produit",
        "quantity": "Quantite chargee",
        "trip_status": "Statut du trajet",
        "gross_amount": "Montant brut",
        "deductions": "Deductions",
        "net_amount": "Montant net",
        "date": "Date",
        "notes": "Notes",
    },
}

_TABLE_STYLE = TableStyle(
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

_SUMMARY_TABLE_STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d5cc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
)


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return ", ".join(f"{k.replace('_', ' ').title()}: {_stringify(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_stringify(v) for v in value)
    return str(value)


def _labels(lang: str) -> dict:
    return LEDGER_PDF_LABELS.get(lang, LEDGER_PDF_LABELS["fr"])


def render_ledger_pdf(
    *,
    company_name: str,
    account_type: str,
    party_name: str,
    export_date,
    summary: dict,
    rows: list[dict],
    lang: str = "fr",
) -> bytes:
    """Generic party-ledger PDF: header + balance-summary table + operation-
    history table. Deliberately generic over dict shape (iterates
    summary.items() / rows[0].keys()) so it never hardcodes a field name -
    each caller adapts its own service's real response into a (summary
    dict, rows list) pair at the call site instead."""
    labels = _labels(lang)
    is_rtl = lang == "ar"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{labels['title']} - {party_name}",
    )
    styles = getSampleStyleSheet()
    align_style = ParagraphStyle("aligned", parent=styles["Normal"], alignment=TA_RIGHT if is_rtl else 0)
    heading_style = ParagraphStyle(
        "headingAligned", parent=styles["Heading2"], alignment=TA_RIGHT if is_rtl else 0
    )

    elements = [
        Paragraph(company_name, styles["Title"]),
        Paragraph(f"{labels['account_type']}: {account_type} — {labels['party']}: {party_name}", align_style),
        Paragraph(f"{labels['export_date']}: {export_date.isoformat()}", align_style),
        Spacer(1, 8 * mm),
        Paragraph(labels["summary"], heading_style),
        Spacer(1, 2 * mm),
    ]

    summary_data = [[key.replace("_", " ").title(), _stringify(value)] for key, value in summary.items()]
    if is_rtl:
        summary_data = [list(reversed(row)) for row in summary_data]
    if summary_data:
        elements.append(Table(summary_data, style=_SUMMARY_TABLE_STYLE))

    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(labels["history"], heading_style))
    elements.append(Spacer(1, 2 * mm))

    if rows:
        fields = list(rows[0].keys())
        header = [field.replace("_", " ").title() for field in fields]
        if is_rtl:
            fields = list(reversed(fields))
            header = list(reversed(header))
        data = [header] + [[_stringify(row.get(field)) for field in fields] for row in rows]
        table = Table(data, repeatRows=1)
        table.setStyle(_TABLE_STYLE)
        elements.append(table)

    doc.build(elements)
    return buffer.getvalue()


def render_trip_settlement_pdf(payment, lang: str = "fr") -> bytes:
    """Single-record ('Reglement par trajet') PDF for one TransportPayment -
    label/value grid, not a multi-row table. Prints exactly the fields the
    task brief lists: trip reference, truck internal_id + plate,
    transporter, client, product, quantity, trip status, gross amount
    (base_amount), deductions (deduction_amount), net (net_amount), date,
    notes.

    TransportPayment itself carries no `date`/`payment_date` or `notes`
    field (see backend/apps/finance/models.py) - `created_at` (settlement
    creation timestamp) is used for "date", and the underlying Trip's
    `notes` field is used for "notes" as the closest available data,
    consistent with printing only what the existing models/services
    already expose (no new field, no new calculation)."""
    labels = _labels(lang)
    is_rtl = lang == "ar"
    trip = payment.trip
    truck = trip.truck

    if trip.client_id:
        client_name = trip.client.name
    elif trip.customer_order_id:
        client_name = trip.customer_order.customer.name
    else:
        client_name = ""

    field_rows = [
        (labels["trip_reference"], trip.reference),
        (labels["truck"], truck.internal_id),
        (labels["plate"], f"{truck.tractor_registration} / {truck.tanker_registration}"),
        (labels["transporter"], payment.transporter.name),
        (labels["client"], client_name),
        (labels["product"], trip.product.name),
        (labels["quantity"], trip.quantity_loaded),
        (labels["trip_status"], trip.status),
        (labels["gross_amount"], payment.base_amount),
        (labels["deductions"], payment.deduction_amount),
        (labels["net_amount"], payment.net_amount),
        (labels["date"], payment.created_at),
        (labels["notes"], trip.notes),
    ]
    data = [[label, _stringify(value)] for label, value in field_rows]
    if is_rtl:
        data = [list(reversed(row)) for row in data]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{labels['settlement_title']} - {trip.reference}",
    )
    styles = getSampleStyleSheet()
    align_style = ParagraphStyle("aligned", parent=styles["Normal"], alignment=TA_RIGHT if is_rtl else 0)

    table = Table(data, colWidths=[60 * mm, 100 * mm])
    table.setStyle(_SUMMARY_TABLE_STYLE)

    elements = [
        Paragraph(labels["settlement_title"], styles["Title"]),
        Paragraph(f"{labels['trip_reference']}: {trip.reference}", align_style),
        Spacer(1, 6 * mm),
        table,
    ]
    doc.build(elements)
    return buffer.getvalue()
