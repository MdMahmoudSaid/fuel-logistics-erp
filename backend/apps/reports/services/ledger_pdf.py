# PDF export for the 3 party ledgers (Grand livre fournisseur/transporteur/
# client), for a single trip's transport settlement ("Reglement par
# trajet"), and for a single customer/supplier payment - docs/superpowers/
# specs/2026-09-04-recette-corrections-design.md Section 5, extended by the
# 2026-09-05 recette-corrections pass (per-payment PDF on all 3 ledgers,
# full-section global export, FR label coverage). No business calculation
# lives here beyond small, isolated, display-only aggregates documented at
# their call site: this module mostly prints dicts/model instances already
# produced elsewhere (SupplierLedgerService.get_ledger /
# TransporterLedgerService.get_ledger, the CustomerViewSet.ledger response,
# and TransportPayment/CustomerPayment/SupplierPayment). Same reportlab
# dependency already used by apps/reports/export.py (rows_to_pdf) - no new
# dependency added.
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
# reversed) while keeping the FRENCH field labels/values as a documented
# fallback, rather than emitting unreadable tofu glyphs. A follow-up
# ticket should add proper Arabic shaping/fonts if the client needs true
# Arabic PDFs.

import datetime
import io
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME, masthead, safe_text

# No per-tenant "company name" setting exists anywhere in this codebase
# (grepped models/settings/frontend branding) - a fixed constant is used
# for the PDF header, matching the generic branding already used
# elsewhere (frontend/index.html <title>).
# Rebrand (2026-09-05): AZUR ÉNERGIE, no "ERP" suffix on PDFs specifically
# (kept only in the browser title / API schema title).
# DEFAULT_COMPANY_NAME now lives in pdf_template (re-exported here: the 3 party-ledger
# views import it from this module).

# Client feedback (2026-09-06): the 3 party ledgers (Grand livre fournisseur/
# transporteur/client) and their per-payment PDFs looked "mal structuree" -
# no logo, no company name, raw un-formatted Decimal figures - next to the
# already-approved apps.reports.services.profit_pdf ("Benefices" PDF, same
# client request). Same logo asset profit_pdf.py already uses, reused here
# rather than duplicated as a second file.

LEDGER_PDF_LABELS = {
    "fr": {
        "title": "Grand livre",
        "account_type": "Type de compte",
        "party": "Compte",
        "export_date": "Date d'export",
        "summary": "Resume des soldes",
        "history": "Historique complet",
        "settlement_title": "Reglement par trajet",
        "trip_reference": "Reference du trajet",
        "truck": "Camion",
        "plate": "Plaque (tracteur / citerne)",
        "transporter": "Transporteur",
        "supplier": "Fournisseur",
        "client": "Client",
        "product": "Produit",
        "quantity": "Quantite chargee",
        "quantity_delivered": "Quantite livree",
        "loss": "Perte",
        "trip_status": "Statut du trajet",
        "gross_amount": "Montant brut",
        "deductions": "Deductions",
        "net_amount": "Montant net",
        "date": "Date",
        "notes": "Notes",
        "status": "Statut",
        "proof": "Justificatif",
        # Per-payment PDF (client/fournisseur) - Section 2, 2026-09-05
        "customer_payment_title": "Paiement client",
        "supplier_payment_title": "Paiement fournisseur",
        "amount_paid": "Montant paye",
        "method": "Methode de paiement",
        "account": "Compte banque/caisse",
        "reference": "Reference",
        "invoice": "Facture(s) concernee(s)",
        "invoice_amount": "Montant facture",
        "already_paid": "Montant deja paye",
        "remaining_balance": "Solde restant",
        "invoice_status": "Statut facture",
        "no_invoice": "Aucune facture (credit non affecte)",
        "order": "Commande(s) fournisseur concernee(s)",
        "order_amount": "Montant commande",
        "advance_used": "Avance utilisee",
        "no_order": "Aucune commande (avance generale)",
        "not_available": "Non applicable",
        # Global export - extra sections, Section 3, 2026-09-05
        "invoices_section": "Liste des factures",
        "payments_section": "Liste des paiements",
        "reliquat_section": "Reliquat par produit",
        "purchase_history_section": "Historique des achats",
        "payments_advances_section": "Paiements et avances",
        "trucks_section": "Camions rattaches",
        "settlements_section": "Reglements par trajet",
        "advances_section": "Avances",
        # Per-invoice PDF (feedback 2026-09-10)
        "invoice_title": "Facture",
        "invoice_number": "Numero de facture",
        "issued_date": "Date d'emission",
        "unit_price": "Prix de vente unitaire",
        "total_amount": "Montant total",
    },
    "en": {
        "title": "Ledger",
        "account_type": "Account type",
        "party": "Account",
        "export_date": "Export date",
        "summary": "Balance summary",
        "history": "Full history",
        "settlement_title": "Trip settlement",
        "trip_reference": "Trip reference",
        "truck": "Truck",
        "plate": "Plate (tractor / tanker)",
        "transporter": "Transporter",
        "supplier": "Supplier",
        "client": "Client",
        "product": "Product",
        "quantity": "Quantity loaded",
        "quantity_delivered": "Quantity delivered",
        "loss": "Loss",
        "trip_status": "Trip status",
        "gross_amount": "Gross amount",
        "deductions": "Deductions",
        "net_amount": "Net amount",
        "date": "Date",
        "notes": "Notes",
        "status": "Status",
        "proof": "Proof",
        "customer_payment_title": "Customer payment",
        "supplier_payment_title": "Supplier payment",
        "amount_paid": "Amount paid",
        "method": "Payment method",
        "account": "Bank/cash account",
        "reference": "Reference",
        "invoice": "Invoice(s) concerned",
        "invoice_amount": "Invoice amount",
        "already_paid": "Amount already paid",
        "remaining_balance": "Remaining balance",
        "invoice_status": "Invoice status",
        "no_invoice": "No invoice (unallocated credit)",
        "order": "Supplier order(s) concerned",
        "order_amount": "Order amount",
        "advance_used": "Advance used",
        "no_order": "No order (general advance)",
        "not_available": "Not applicable",
        "invoices_section": "Invoice list",
        "payments_section": "Payment list",
        "reliquat_section": "Remaining balance by product",
        "purchase_history_section": "Purchase history",
        "payments_advances_section": "Payments and advances",
        "trucks_section": "Attached trucks",
        "settlements_section": "Trip settlements",
        "advances_section": "Advances",
        "invoice_title": "Invoice",
        "invoice_number": "Invoice number",
        "issued_date": "Issued date",
        "unit_price": "Unit selling price",
        "total_amount": "Total amount",
    },
    # AR: labels intentionally kept in French pending an embedded
    # Arabic-capable font + reshaping/bidi support - see module docstring.
    "ar": {
        "title": "Grand livre",
        "account_type": "Type de compte",
        "party": "Compte",
        "export_date": "Date d'export",
        "summary": "Resume des soldes",
        "history": "Historique complet",
        "settlement_title": "Reglement par trajet",
        "trip_reference": "Reference du trajet",
        "truck": "Camion",
        "plate": "Plaque (tracteur / citerne)",
        "transporter": "Transporteur",
        "supplier": "Fournisseur",
        "client": "Client",
        "product": "Produit",
        "quantity": "Quantite chargee",
        "quantity_delivered": "Quantite livree",
        "loss": "Perte",
        "trip_status": "Statut du trajet",
        "gross_amount": "Montant brut",
        "deductions": "Deductions",
        "net_amount": "Montant net",
        "date": "Date",
        "notes": "Notes",
        "status": "Statut",
        "proof": "Justificatif",
        "customer_payment_title": "Paiement client",
        "supplier_payment_title": "Paiement fournisseur",
        "amount_paid": "Montant paye",
        "method": "Methode de paiement",
        "account": "Compte banque/caisse",
        "reference": "Reference",
        "invoice": "Facture(s) concernee(s)",
        "invoice_amount": "Montant facture",
        "already_paid": "Montant deja paye",
        "remaining_balance": "Solde restant",
        "invoice_status": "Statut facture",
        "no_invoice": "Aucune facture (credit non affecte)",
        "order": "Commande(s) fournisseur concernee(s)",
        "order_amount": "Montant commande",
        "advance_used": "Avance utilisee",
        "no_order": "Aucune commande (avance generale)",
        "not_available": "Non applicable",
        "invoices_section": "Liste des factures",
        "payments_section": "Liste des paiements",
        "reliquat_section": "Reliquat par produit",
        "purchase_history_section": "Historique des achats",
        "payments_advances_section": "Paiements et avances",
        "trucks_section": "Camions rattaches",
        "settlements_section": "Reglements par trajet",
        "advances_section": "Avances",
        "invoice_title": "Facture",
        "invoice_number": "Numero de facture",
        "issued_date": "Date d'emission",
        "unit_price": "Prix de vente unitaire",
        "total_amount": "Montant total",
    },
}

# Generic dict-key -> printable-column-header translation, used for both
# `summary.items()` keys and `rows[0].keys()` table headers in
# render_ledger_pdf (2026-09-05 language fix): before this map, those two
# spots fell back to `key.replace("_", " ").title()` unconditionally,
# which prints the raw English/snake_case field name (e.g. "Outstanding
# Balance", "Net Balance") even when lang="fr" - the actual root cause of
# "plusieurs mots-clefs restent en anglais" in the client's recette
# feedback. Only used when lang is "fr"/"ar" (falls through to the
# existing, already-correct `.title()` behaviour for lang="en").
FIELD_LABELS_FR = {
    "id": "Identifiant",
    "label": "Libelle",
    "type": "Type",
    "date": "Date",
    "amount": "Montant",
    "reference": "Reference",
    "note": "Note",
    "notes": "Notes",
    "proof_url": "Justificatif",
    "proof": "Justificatif",
    "status": "Statut",
    "outstanding_balance": "Solde impaye",
    "total_due": "Total du",
    "open_advances": "Avances ouvertes",
    "net_balance": "Solde net",
    "last_advance": "Derniere avance",
    "last_payment": "Dernier paiement",
    "total_purchased": "Total achete",
    "total_paid": "Total paye",
    "total_invoiced": "Total facture",
    "total_received": "Total encaisse",
    "open_invoices": "Factures ouvertes",
    "invoice_number": "Facture",
    "issued_date": "Date d'emission",
    "quantity_loaded": "Qté chargée",
    "delivered_quantity": "Qté reçue",
    "total_amount": "Montant total",
    "outstanding": "Solde restant",
    "payment_date": "Date de paiement",
    "method": "Methode de paiement",
    "indirect": "Indirect",
    "is_advance": "Avance",
    "product_name": "Produit",
    "product": "Produit",
    "total_reliquat": "Reliquat",
    "purchase_date": "Date d'achat",
    "quantity_litres": "Quantite (L)",
    "unit_price": "Prix unitaire",
    "internal_id": "Camion",
    "tractor_registration": "Plaque tracteur",
    "tanker_registration": "Plaque citerne",
    "trip_reference": "Trajet",
    "base_amount": "Montant brut",
    "deduction_amount": "Deduction",
    "net_amount": "Montant net",
    "settled": "Solde",
    "advance_applied": "Avance appliquee",
}

# Enum/code VALUE -> printable-value translation (2026-09-05 language fix):
# the "type"/"status"/"method" COLUMNS above hold raw model choice codes
# (e.g. "PAID", "advance_given", "CASH") as their cell values, not just
# their header - _stringify() printed those verbatim regardless of lang,
# which is the other half of the English-leak bug. Same fr-only/ar-falls-
# back-to-fr policy as FIELD_LABELS_FR above.
VALUE_LABELS_FR = {
    # SupplierLedgerService/TransporterLedgerService entry "type"
    "advance_given": "Avance versee",
    "debt_created": "Dette creee",
    "advance_consumed": "Avance consommee",
    "payment": "Paiement",
    "invoice": "Facture",
    # Invoice.Status / SupplierOrder.Status / TransportPayment.Status
    # (union - no colliding meaning across these enums)
    "DRAFT": "Brouillon",
    "VALIDATED": "Validee",
    "CONFIRMED": "Confirmee",
    "PARTIALLY_PAID": "Partiellement paye",
    "PAID": "Paye",
    "CANCELLED": "Annule",
    "PLANNED": "Planifie",
    "PAYABLE": "A payer",
    "DEDUCTION_APPLIED": "Deduction appliquee",
    # Trip.Status (frontend/src/locales/fr.json trips.status - reused
    # verbatim here so both sides of the app use the same French wording)
    "ASSIGNED": "Affecte",
    "SENT_FOR_LOADING": "Envoye au chargement",
    "LOADING": "Chargement en cours",
    "LOADED": "Charge",
    "ROAD_TRANSIT": "Transit routiere",
    "IN_TRANSIT": "En transit",
    "BORDER": "Frontiere",
    "CUSTOMS": "Douane",
    "GOING_TO_COMPANY_STOCK": "En route vers stock entreprise",
    "ARRIVED_AT_COMPANY_STOCK": "Arrive au stock entreprise",
    "STOCKED": "Stocke",
    "GOING_TO_CLIENT": "En route vers le client",
    "ARRIVED_AT_CLIENT": "Arrive chez le client",
    "QUANTITY_CONTROL": "Controle de quantite",
    "DELIVERED": "Livre",
    "COMPLETED": "Termine",
    "BLOCKED": "Bloque",
    # CustomerPayment.Method / SupplierPayment.Method
    "CASH": "Especes",
    "BANK_TRANSFER": "Virement bancaire",
    "CHEQUE": "Cheque",
    "OTHER": "Autre",
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


def _bold_row(row_index: int):
    """A TableStyle command bolding one full row (label + value column) of
    a 2-column label/value table - same helper as
    apps.reports.services.profit_pdf._bold_row, duplicated per this
    module's self-contained-helpers convention (see module docstring)."""
    return ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold")


# Balance keys that represent a party's final, bottom-line figure across
# the 3 ledgers' differently-shaped summary dicts (supplier/transporter:
# "net_balance"; customer: "outstanding_balance") - bolded in the summary
# table below so the one number an operator actually needs stands out,
# same idea as profit_pdf's _bold_row usage on its own subtotal rows.
_FINAL_BALANCE_KEYS = {"net_balance", "outstanding_balance"}

# Field-name -> unit registry (2026-09-06 restructure), used only by the
# generic dict-shaped tables in render_ledger_pdf (summary.items() /
# _section_table) where the raw field key is available at format time -
# every one of these names surveyed directly from the 3 call sites
# (apps.suppliers/apps.transport/apps.customers views.py ledger_pdf
# actions) plus SupplierLedgerService/TransporterLedgerService.get_ledger.
# The single-record PDFs below (settlement/customer-payment/supplier-
# payment) format their own known fields explicitly instead, since they
# only have a human label there, not the raw key.
_MONEY_FIELDS = {
    "amount", "total_due", "open_advances", "net_balance", "base_amount",
    "deduction_amount", "net_amount", "total_amount", "total_invoiced",
    "total_received", "outstanding_balance", "outstanding", "total_purchased",
    "total_paid", "invoice_amount", "already_paid", "remaining_balance",
    "order_amount", "advance_used", "amount_paid",
}
_QUANTITY_FIELDS = {
    "quantity_litres", "total_reliquat", "quantity", "quantity_delivered", "loss",
    "quantity_loaded", "delivered_quantity",
}
_UNIT_PRICE_FIELDS = {"unit_price"}


def _format_money(value) -> str:
    """`1 250 000 XOF` - rounded to the nearest unit, space-grouped, same
    convention as the frontend's formatMoney() (utils/currency.ts) and
    apps.reports.services.profit_pdf._format_money, so every PDF in the app
    prints a given amount identically instead of each renderer inventing
    its own number formatting."""
    if value is None or value == "":
        return ""
    amount = int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{amount:,}".replace(",", " ") + " XOF"


def _format_quantity(value) -> str:
    """`45 000 L` - same rounding/grouping convention as formatQuantity()."""
    if value is None or value == "":
        return ""
    amount = int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{amount:,}".replace(",", " ") + " L"


def _format_unit_money(value) -> str:
    """`500,0000 XOF/L` - 4-decimal French-comma per-litre price, matching
    the frontend's formatUnitMoney() and profit_pdf's own
    _format_unit_money (2026-09-06 precision fix - see that module for the
    full rationale)."""
    if value is None or value == "":
        return ""
    quantized = Decimal(value).quantize(Decimal("0.0001"))
    formatted = f"{quantized:,.4f}"
    integer_part, _, decimal_part = formatted.partition(".")
    return f"{integer_part.replace(',', ' ')},{decimal_part} XOF/L"


def _stringify(value, lang: str = "fr") -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        if lang in ("fr", "ar"):
            return "Oui" if value else "Non"
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.datetime):
        # Bug fix (found in visual review, 2026-09-06): a bare
        # datetime.isoformat() prints microseconds and a UTC "+00:00"
        # offset (e.g. "2026-09-06T14:09:21.164891+00:00") for a timestamp
        # field like TransportPayment.created_at - noise no operator
        # needs, and the raw UTC offset doesn't match the app's display
        # timezone (settings.TIME_ZONE = "Africa/Dakar"). Converted with
        # timezone.localtime (same helper apps.reports.date_range already
        # uses) before dropping to seconds precision, no offset.
        local_value = timezone.localtime(value) if timezone.is_aware(value) else value
        return local_value.replace(microsecond=0, tzinfo=None).isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return ", ".join(
            f"{_translate_key(k, lang)}: {_format_field_value(k, v, lang)}" for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return ", ".join(_stringify(v, lang) for v in value)
    text = str(value)
    if lang in ("fr", "ar") and text in VALUE_LABELS_FR:
        return VALUE_LABELS_FR[text]
    return text


def _format_field_value(key: str, value, lang: str = "fr") -> str:
    """Like _stringify, but money/quantity/unit-price fields (looked up by
    their raw dict key against the _MONEY_FIELDS/_QUANTITY_FIELDS/
    _UNIT_PRICE_FIELDS registries above) print through the same formatted
    convention as every other PDF in the app, instead of a bare Decimal's
    str() (e.g. "1250000.00" instead of "1 250 000 XOF") - the single
    biggest contributor to the "mal structuree" client feedback on these 3
    ledger PDFs. Only used where the raw field key is available (the
    generic dict-shaped summary/rows/extra_sections in render_ledger_pdf);
    falls back to _stringify for every other key/type."""
    if value is None or value == "":
        return ""
    if key in _MONEY_FIELDS and not isinstance(value, (dict, list, tuple, bool)):
        return _format_money(value)
    if key in _QUANTITY_FIELDS and not isinstance(value, (dict, list, tuple, bool)):
        return _format_quantity(value)
    if key in _UNIT_PRICE_FIELDS and not isinstance(value, (dict, list, tuple, bool)):
        return _format_unit_money(value)
    return _stringify(value, lang)


# Kept under its historical name: the docstring/rationale now lives in
# pdf_template.safe_text.
_safe_paragraph_text = safe_text


def _translate_key(key: str, lang: str) -> str:
    if lang in ("fr", "ar") and key in FIELD_LABELS_FR:
        return FIELD_LABELS_FR[key]
    return key.replace("_", " ").title()


def _labels(lang: str) -> dict:
    return LEDGER_PDF_LABELS.get(lang, LEDGER_PDF_LABELS["fr"])


def get_ledger_pdf_labels(lang: str) -> dict:
    """Public accessor for LEDGER_PDF_LABELS, used by the 3 party-ledger
    views to translate the section titles they pass into `extra_sections`
    (their own list of section names - e.g. "Reliquat par produit" - isn't
    something this generic renderer can know on its own)."""
    return _labels(lang)


def _cell_style(lang: str, *, header: bool = False, numeric: bool = False) -> ParagraphStyle:
    """Small Paragraph style for a Table cell (2026-09-06 restructure -
    see _section_table). Header cells need white text to stay legible
    against _TABLE_STYLE's dark BACKGROUND - a TableStyle TEXTCOLOR command
    has no effect once a cell holds a Paragraph, since the Paragraph draws
    with its own style, not the cell's. `numeric` right-aligns a money/
    quantity/unit-price column (matching every other PDF's convention for
    figures) - a plain TableStyle ALIGN command has no visible effect on a
    Paragraph cell, since the Paragraph always fills its whole column
    width; the text alignment has to live in the Paragraph's own style."""
    return ParagraphStyle(
        f"cell-{'header' if header else 'body'}-{'num' if numeric else 'txt'}-{lang}",
        fontName="Helvetica-Bold" if header else "Helvetica",
        fontSize=8,
        leading=9.5,
        textColor=colors.white if header else colors.HexColor("#12171c"),
        alignment=TA_RIGHT if (lang == "ar" or numeric) else 0,
    )


def _pdf_masthead(*, company_name: str, doc_title: str, styles, heading_style) -> list:
    """Logo + company name + document-title heading, shared by every PDF this
    module renders - see pdf_template.masthead."""
    return masthead(company_name=company_name, doc_title=doc_title, styles=styles, heading_style=heading_style)


_PAGE_CONTENT_WIDTH = A4[0] - 30 * mm


def _doc_template(buffer, *, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=title,
    )


def _section_table(title: str, rows: list[dict], *, lang: str, is_rtl: bool, heading_style):
    """One labeled Paragraph + Table block for a section of rows, or an
    empty list if there is nothing to print - callers just extend()
    elements with the result, so an empty section never crashes and never
    prints an empty table.

    Restructure (2026-09-06, client feedback: these tables read as "mal
    structuree"): every cell is now a Paragraph inside an evenly-split,
    explicit-width column instead of a bare string in an auto-sized one -
    a long free-text value (a party/product name, a note) used to force
    its own column as wide as its content, which could overflow the page
    edge on a wide section; wrapped in a Paragraph with a fixed column
    width it wraps onto a second line instead. Money/quantity/unit-price
    columns (by field name - _MONEY_FIELDS et al.) go through
    _format_field_value and render right-aligned, the same convention
    every other PDF in the app uses for figures."""
    if not rows:
        return []
    fields = list(rows[0].keys())
    header_text = [_translate_key(field, lang) for field in fields]
    if is_rtl:
        fields = list(reversed(fields))
        header_text = list(reversed(header_text))

    numeric_fields = _MONEY_FIELDS | _QUANTITY_FIELDS | _UNIT_PRICE_FIELDS
    header_style = _cell_style(lang, header=True)
    body_styles = [_cell_style(lang, numeric=field in numeric_fields) for field in fields]

    header = [Paragraph(_safe_paragraph_text(text), header_style) for text in header_text]
    data = [header] + [
        [
            Paragraph(_safe_paragraph_text(_format_field_value(field, row.get(field), lang)), body_styles[i])
            for i, field in enumerate(fields)
        ]
        for row in rows
    ]
    col_width = _PAGE_CONTENT_WIDTH / len(fields)
    table = Table(data, repeatRows=1, colWidths=[col_width] * len(fields))
    table.setStyle(_TABLE_STYLE)
    return [
        Spacer(1, 8 * mm),
        Paragraph(_safe_paragraph_text(title), heading_style),
        Spacer(1, 2 * mm),
        table,
    ]


def render_ledger_pdf(
    *,
    company_name: str,
    account_type: str,
    party_name: str,
    export_date,
    summary: dict,
    rows: list[dict],
    lang: str = "fr",
    extra_sections: list[dict] | None = None,
) -> bytes:
    """Generic party-ledger PDF: header + balance-summary table + one
    "history" table (`rows`) + any number of additional labeled sections
    (`extra_sections`, each `{"title": str, "rows": list[dict]}`) - Section
    3 of the 2026-09-05 recette-corrections pass added `extra_sections` so
    each of the 3 ledgers can print every section already visible on its
    page (invoices/payments for client, reliquat/purchase-history/payments
    for fournisseur, trucks/settlements/advances for transporteur) rather
    than only the merged chronological history. Deliberately generic over
    dict shape (iterates summary.items() / rows[0].keys()) so it never
    hardcodes a field name - each caller adapts its own service's real
    response into a (summary dict, rows list, extra_sections list) shape
    at the call site instead. A section with an empty rows list is simply
    skipped (see _section_table) - export never crashes on missing data."""
    labels = _labels(lang)
    is_rtl = lang == "ar"

    buffer = io.BytesIO()
    doc = _doc_template(buffer, title=f"{labels['title']} - {party_name}")
    styles = getSampleStyleSheet()
    align_style = ParagraphStyle("aligned", parent=styles["Normal"], alignment=TA_RIGHT if is_rtl else 0)
    # (doc's own `title=` above is PDF metadata, not markup-parsed - no
    # escaping needed there, only for the Paragraph flowables below.)
    heading_style = ParagraphStyle(
        "headingAligned", parent=styles["Heading2"], alignment=TA_RIGHT if is_rtl else 0
    )

    # Security fix (2026-09-06): party_name (customer/supplier/transporter
    # .name) is free text an operator typed into a form - escape before it
    # reaches Paragraph, see _safe_paragraph_text's docstring.
    safe_party_name = _safe_paragraph_text(party_name)
    # Restructure (2026-09-06): logo + company name + "Grand livre" title
    # heading - previously this PDF printed the company name but never the
    # document's own title, and no logo at all (client feedback: "ne
    # contient pas les logos, ne contient pas le nom d'entreprise").
    elements = _pdf_masthead(
        company_name=company_name, doc_title=labels["title"], styles=styles, heading_style=heading_style
    )
    elements += [
        Paragraph(f"{labels['account_type']}: {account_type} — {labels['party']}: {safe_party_name}", align_style),
        Paragraph(f"{labels['export_date']}: {export_date.isoformat()}", align_style),
        Spacer(1, 8 * mm),
        Paragraph(labels["summary"], heading_style),
        Spacer(1, 2 * mm),
    ]

    summary_data = [
        [_translate_key(key, lang), _format_field_value(key, value, lang)] for key, value in summary.items()
    ]
    bold_rows = [index for index, key in enumerate(summary.keys()) if key in _FINAL_BALANCE_KEYS]
    if is_rtl:
        summary_data = [list(reversed(row)) for row in summary_data]
    if summary_data:
        summary_table = Table(summary_data, colWidths=[90 * mm, 90 * mm])
        summary_table.setStyle(_SUMMARY_TABLE_STYLE)
        if bold_rows:
            summary_table.setStyle(TableStyle([_bold_row(index) for index in bold_rows]))
        elements.append(summary_table)

    elements.extend(
        _section_table(labels["history"], rows, lang=lang, is_rtl=is_rtl, heading_style=heading_style)
    )
    for section in extra_sections or []:
        elements.extend(
            _section_table(
                section["title"], section["rows"], lang=lang, is_rtl=is_rtl, heading_style=heading_style
            )
        )

    doc.build(elements)
    return buffer.getvalue()


def _label_value_style(lang: str, *, bold: bool = False) -> ParagraphStyle:
    """Label/value grid cell style for _label_value_pdf - separate from
    _cell_style (which assumes the dark-header history-table look): this
    grid has no shaded header row, just a bold label column next to a
    plain value column."""
    return ParagraphStyle(
        f"labelvalue-{'bold' if bold else 'normal'}-{lang}",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#12171c"),
        alignment=TA_RIGHT if lang == "ar" else 0,
    )


def _label_value_pdf(*, title: str, field_rows: list[tuple[str, object]], lang: str) -> bytes:
    """Shared layout for the single-record PDFs below (trip settlement,
    customer payment, supplier payment): logo + company name + title +
    one label/value grid. Extracted from the pre-2026-09-05
    render_trip_settlement_pdf body so all 3 per-record PDFs share one
    layout instead of copy-pasting the SimpleDocTemplate/table boilerplate
    three times.

    Restructure (2026-09-06, client feedback: these had no logo/company
    name at all, unlike the ledger PDFs above): now goes through the same
    _pdf_masthead every other PDF in this module uses. Each value cell is
    also wrapped in an escaped Paragraph (was a bare string) so a long
    free-text value (e.g. Trip.notes) wraps within its fixed 100mm column
    instead of overflowing it."""
    is_rtl = lang == "ar"
    label_style = _label_value_style(lang, bold=True)
    value_style = _label_value_style(lang, bold=False)
    data = [
        [
            Paragraph(_safe_paragraph_text(label), label_style),
            Paragraph(_safe_paragraph_text(_stringify(value, lang)), value_style),
        ]
        for label, value in field_rows
    ]
    if is_rtl:
        data = [list(reversed(row)) for row in data]

    buffer = io.BytesIO()
    doc = _doc_template(buffer, title=title)
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "headingAligned", parent=styles["Heading2"], alignment=TA_RIGHT if is_rtl else 0
    )

    table = Table(data, colWidths=[60 * mm, 100 * mm])
    table.setStyle(_SUMMARY_TABLE_STYLE)

    elements = _pdf_masthead(
        company_name=DEFAULT_COMPANY_NAME, doc_title=title, styles=styles, heading_style=heading_style
    )
    elements += [Spacer(1, 6 * mm), table]
    doc.build(elements)
    return buffer.getvalue()


def render_trip_settlement_pdf(payment, lang: str = "fr") -> bytes:
    """Single-record ('Reglement par trajet') PDF for one TransportPayment -
    label/value grid, not a multi-row table. Prints the fields the Section
    2 task brief lists (2026-09-05 pass added fournisseur, quantite livree,
    perte, statut (payment.status, distinct from the pre-existing "statut
    du trajet"), justificatif and date d'export - the rest already existed
    from the original 2026-09-04 pass): trip reference, truck internal_id +
    plate, transporter, fournisseur, client, product, quantity chargee,
    quantity livree, perte, trip status, payment status, gross amount
    (base_amount), deductions (deduction_amount), net (net_amount), date,
    justificatif, date d'export, notes.

    TransportPayment itself carries no `date`/`payment_date` field (see
    backend/apps/finance/models.py) - `created_at` (settlement creation
    timestamp) is used for "date", and the underlying Trip's `notes` field
    is used for "notes" as the closest available data, consistent with
    printing only what the existing models/services already expose (no new
    field, no new calculation beyond the isolated proof_url lookup below,
    the same lookup SupplierPaymentSerializer.get_proof_url already uses
    for a different model)."""
    labels = _labels(lang)
    trip = payment.trip
    truck = trip.truck

    if trip.client_id:
        client_name = trip.client.name
    elif trip.customer_order_id:
        client_name = trip.customer_order.customer.name
    else:
        client_name = ""

    delivery_control = getattr(trip, "delivery_control", None)
    quantity_delivered = delivery_control.received_quantity if delivery_control else None
    loss = delivery_control.loss_quantity if delivery_control else None

    # Same lookup SupplierPaymentSerializer.get_proof_url already uses
    # (backend/apps/finance/serializers.py) for a different payment model -
    # TransportPayment has no direct document FK either, only the
    # TreasuryTransaction posted against it by
    # ControlledDebtPaymentService.
    from django.contrib.contenttypes.models import ContentType

    from apps.finance.models import TreasuryTransaction

    payment_ct = ContentType.objects.get_for_model(type(payment))
    txn = (
        TreasuryTransaction.objects.filter(
            source_content_type=payment_ct, source_object_id=payment.id, document__isnull=False
        )
        .select_related("document")
        .order_by("-date", "-id")
        .first()
    )
    proof = txn.document.file.url if txn and txn.document.file else None

    field_rows = [
        (labels["trip_reference"], trip.reference),
        (labels["truck"], truck.internal_id),
        (labels["plate"], f"{truck.tractor_registration} / {truck.tanker_registration}"),
        (labels["transporter"], payment.transporter.name),
        (labels["supplier"], trip.supplier.name if trip.supplier_id else ""),
        (labels["client"], client_name),
        (labels["product"], trip.product.name),
        (labels["quantity"], _format_quantity(trip.quantity_loaded)),
        (labels["quantity_delivered"], _format_quantity(quantity_delivered)),
        (labels["loss"], _format_quantity(loss)),
        (labels["trip_status"], trip.status),
        (labels["status"], payment.status),
        (labels["gross_amount"], _format_money(payment.base_amount)),
        (labels["deductions"], _format_money(payment.deduction_amount)),
        (labels["net_amount"], _format_money(payment.net_amount)),
        (labels["date"], payment.created_at),
        (labels["proof"], proof or labels["not_available"]),
        (labels["export_date"], datetime.date.today()),
        (labels["notes"], trip.notes),
    ]
    return _label_value_pdf(
        title=f"{labels['settlement_title']} - {trip.reference}", field_rows=field_rows, lang=lang
    )


def render_invoice_pdf(invoice, lang: str = "fr") -> bytes:
    """Single-record PDF for one Invoice (feedback 2026-09-10: the client
    ledger's Factures table needed the same per-row PDF export the
    Paiements table already had). Same label/value grid layout as
    render_trip_settlement_pdf/render_customer_payment_pdf, printing the
    same fields already shown on InvoiceDetail.vue plus the truck plates
    (Sale.trip.truck) - same "the client wants to see which truck loaded
    this invoice" ask that also added Sale.truck_plates to the API."""
    labels = _labels(lang)
    sale = invoice.sale
    trip = sale.trip
    truck = trip.truck

    field_rows = [
        (labels["invoice_number"], invoice.invoice_number),
        (labels["client"], sale.customer.name),
        (labels["product"], sale.product.name),
        (labels["trip_reference"], trip.reference),
        (labels["truck"], truck.internal_id),
        (labels["plate"], f"{truck.tractor_registration} / {truck.tanker_registration}"),
        (labels["quantity"], _format_quantity(trip.quantity_loaded)),
        (labels["quantity_delivered"], _format_quantity(sale.delivered_quantity)),
        (labels["unit_price"], _format_unit_money(sale.unit_selling_price)),
        (labels["total_amount"], _format_money(invoice.total_amount)),
        (labels["invoice_status"], invoice.status),
        (labels["issued_date"], invoice.issued_date),
        (labels["export_date"], datetime.date.today()),
    ]
    return _label_value_pdf(
        title=f"{labels['invoice_title']} - {invoice.invoice_number}",
        field_rows=field_rows,
        lang=lang,
    )


def render_customer_payment_pdf(payment, lang: str = "fr") -> bytes:
    """Single-record PDF for one CustomerPayment (Section 2, 2026-09-05):
    header label/value grid (client, date, montant paye, methode, compte,
    reference, justificatif, date d'export) followed by one row per
    allocated invoice (montant facture / montant deja paye / solde restant
    / statut), reusing PaymentAllocationService.get_invoice_outstanding -
    the same outstanding computation CustomerViewSet.ledger() already uses
    - so this PDF can never show a different balance than the on-screen
    ledger. An unallocated payment (pure credit, no invoice) prints one
    explanatory row instead of an empty table."""
    from apps.finance.services import PaymentAllocationService

    labels = _labels(lang)
    is_rtl = lang == "ar"

    account = payment.bank_account.name if payment.bank_account_id else (
        payment.cash_account.name if payment.cash_account_id else labels["not_available"]
    )

    header_rows = [
        (labels["client"], payment.customer.name),
        (labels["date"], payment.payment_date),
        (labels["amount_paid"], _format_money(payment.amount)),
        (labels["method"], payment.method),
        (labels["account"], account),
        (labels["reference"], payment.reference or ""),
    ]

    allocations = list(payment.allocations.select_related("invoice").all())
    invoice_rows = []
    for allocation in allocations:
        invoice = allocation.invoice
        if invoice is None:
            invoice_rows.append(
                {
                    labels["invoice"]: labels["no_invoice"],
                    labels["invoice_amount"]: "",
                    labels["already_paid"]: "",
                    labels["remaining_balance"]: "",
                    labels["invoice_status"]: "",
                }
            )
            continue
        outstanding = PaymentAllocationService.get_invoice_outstanding(invoice)
        already_paid = invoice.total_amount - outstanding
        invoice_rows.append(
            {
                labels["invoice"]: invoice.invoice_number,
                labels["invoice_amount"]: _format_money(invoice.total_amount),
                labels["already_paid"]: _format_money(already_paid),
                labels["remaining_balance"]: _format_money(outstanding),
                labels["invoice_status"]: _stringify(invoice.status, lang),
            }
        )

    buffer = io.BytesIO()
    # Security fix (2026-09-06): payment.customer.name is free text - only
    # the Paragraph rendering below needs escaping (doc's own `title=` is
    # PDF metadata, not markup-parsed).
    title = f"{labels['customer_payment_title']} - {payment.customer.name}"
    doc = _doc_template(buffer, title=title)
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "headingAligned", parent=styles["Heading2"], alignment=TA_RIGHT if is_rtl else 0
    )

    label_style = _label_value_style(lang, bold=True)
    value_style = _label_value_style(lang, bold=False)
    header_data = [
        [
            Paragraph(_safe_paragraph_text(label), label_style),
            Paragraph(_safe_paragraph_text(_stringify(value, lang)), value_style),
        ]
        for label, value in header_rows
    ]
    if is_rtl:
        header_data = [list(reversed(row)) for row in header_data]
    header_table = Table(header_data, colWidths=[60 * mm, 100 * mm])
    header_table.setStyle(_SUMMARY_TABLE_STYLE)

    elements = _pdf_masthead(
        company_name=DEFAULT_COMPANY_NAME, doc_title=title, styles=styles, heading_style=heading_style
    )
    elements += [Spacer(1, 6 * mm), header_table]
    if invoice_rows:
        columns = list(invoice_rows[0].keys())
        if is_rtl:
            columns = list(reversed(columns))
        money_columns = {labels["invoice_amount"], labels["already_paid"], labels["remaining_balance"]}
        header_row_style = _cell_style(lang, header=True)
        column_styles = [_cell_style(lang, numeric=column in money_columns) for column in columns]
        table_data = [[Paragraph(_safe_paragraph_text(column), header_row_style) for column in columns]] + [
            [
                Paragraph(_safe_paragraph_text(row[column]), column_styles[i])
                for i, column in enumerate(columns)
            ]
            for row in invoice_rows
        ]
        invoices_table = Table(table_data, repeatRows=1, colWidths=[_PAGE_CONTENT_WIDTH / len(columns)] * len(columns))
        invoices_table.setStyle(_TABLE_STYLE)
        elements.extend(
            [Spacer(1, 8 * mm), Paragraph(labels["invoice"], heading_style), Spacer(1, 2 * mm), invoices_table]
        )
    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph(f"{labels['export_date']}: {datetime.date.today().isoformat()}", styles["Normal"]))

    doc.build(elements)
    return buffer.getvalue()


def render_supplier_payment_pdf(payment, lang: str = "fr") -> bytes:
    """Single-record PDF for one SupplierPayment (Section 2, 2026-09-05):
    header label/value grid (fournisseur, date, montant paye, methode,
    compte, reference, justificatif, date d'export), followed by the
    concerned order's own fields (produit, quantite, montant commande,
    avance utilisee, solde restant, statut) when the payment is tied to
    one (`supplier_order` is nullable - a general advance has none).

    "Solde restant" is the order's total_amount minus every non-advance
    SupplierPayment ever recorded against it (all of them, not just this
    one) - a small, isolated, display-only aggregate scoped to this PDF,
    the same shape as the "avance utilisee" aggregate below (mirrors the
    AdvanceConsumption-sum pattern TransporterViewSet.ledger() already
    uses for its own "advances_applied" figure, just scoped to one order
    instead of one transporter's whole history)."""
    from django.db.models import Sum

    from apps.finance.models import AdvanceConsumption

    labels = _labels(lang)
    is_rtl = lang == "ar"

    account = payment.bank_account.name if payment.bank_account_id else (
        payment.cash_account.name if payment.cash_account_id else labels["not_available"]
    )

    header_rows = [
        (labels["supplier"], payment.supplier.name),
        (labels["date"], payment.payment_date),
        (labels["amount_paid"], _format_money(payment.amount)),
        (labels["method"], payment.method),
        (labels["account"], account),
        (labels["reference"], payment.reference or ""),
    ]

    order = payment.supplier_order
    order_rows: list[tuple[str, object]]
    if order is None:
        order_rows = [(labels["order"], labels["no_order"])]
    else:
        from django.contrib.contenttypes.models import ContentType

        order_ct = ContentType.objects.get_for_model(type(order))
        advance_used = (
            AdvanceConsumption.objects.filter(
                debt_content_type=order_ct, debt_object_id=order.id, reversed_at__isnull=True
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        # Bug fix (client business rule, confirmed 2026-09-06): reuse
        # ControlledDebtPaymentService.describe_supplier_order - the single
        # source of truth for a supplier order's debt (priced on quantity
        # actually loaded, not the full order) and its remaining balance -
        # rather than recomputing "order.total_amount - paid" here, which
        # both duplicated the formula and had gone stale after that fix.
        from apps.finance.services import ControlledDebtPaymentService

        order_debt = ControlledDebtPaymentService.describe_supplier_order(order)
        remaining_balance = order_debt["remaining_amount"]
        order_rows = [
            (labels["order"], order.reference),
            (labels["product"], order.product.name),
            (labels["quantity"], _format_quantity(order.quantity_litres)),
            (labels["order_amount"], _format_money(order.total_amount)),
            (labels["advance_used"], _format_money(advance_used)),
            (labels["remaining_balance"], _format_money(remaining_balance)),
            (labels["status"], order.status),
        ]

    buffer = io.BytesIO()
    # Security fix (2026-09-06): payment.supplier.name is free text - only
    # the Paragraph rendering below needs escaping (doc's own `title=` is
    # PDF metadata, not markup-parsed).
    title = f"{labels['supplier_payment_title']} - {payment.supplier.name}"
    doc = _doc_template(buffer, title=title)
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "headingAligned", parent=styles["Heading2"], alignment=TA_RIGHT if is_rtl else 0
    )

    label_style = _label_value_style(lang, bold=True)
    value_style = _label_value_style(lang, bold=False)

    def _row_pairs(rows):
        return [
            [
                Paragraph(_safe_paragraph_text(label), label_style),
                Paragraph(_safe_paragraph_text(_stringify(value, lang)), value_style),
            ]
            for label, value in rows
        ]

    header_data = _row_pairs(header_rows)
    order_data = _row_pairs(order_rows)
    if is_rtl:
        header_data = [list(reversed(row)) for row in header_data]
        order_data = [list(reversed(row)) for row in order_data]

    header_table = Table(header_data, colWidths=[60 * mm, 100 * mm])
    header_table.setStyle(_SUMMARY_TABLE_STYLE)
    order_table = Table(order_data, colWidths=[60 * mm, 100 * mm])
    order_table.setStyle(_SUMMARY_TABLE_STYLE)

    elements = _pdf_masthead(
        company_name=DEFAULT_COMPANY_NAME, doc_title=title, styles=styles, heading_style=heading_style
    )
    elements += [
        Spacer(1, 6 * mm),
        header_table,
        Spacer(1, 8 * mm),
        order_table,
        Spacer(1, 6 * mm),
        Paragraph(f"{labels['export_date']}: {datetime.date.today().isoformat()}", styles["Normal"]),
    ]
    doc.build(elements)
    return buffer.getvalue()
