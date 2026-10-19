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

from apps.reports.services.pdf_template import (
    DEFAULT_COMPANY_NAME,
    FOOTER_MARGIN,
    masthead,
    numbered_canvas_cls,
    safe_text,
)

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
        "summary": "Résumé des soldes",
        "history": "Historique complet",
        "settlement_title": "Règlement par trajet",
        "trip_reference": "Référence du trajet",
        "truck": "Camion",
        "plate": "Plaque (tracteur / citerne)",
        "transporter": "Transporteur",
        "supplier": "Fournisseur",
        "client": "Client",
        "product": "Produit",
        "quantity": "Quantité chargée",
        "quantity_delivered": "Quantité livrée",
        "loss": "Perte",
        "trip_status": "Statut du trajet",
        "gross_amount": "Montant brut",
        "deductions": "Déductions",
        "net_amount": "Montant net",
        "date": "Date",
        "notes": "Notes",
        "status": "Statut",
        "proof": "Justificatif",
        # Per-payment PDF (client/fournisseur) - Section 2, 2026-09-05
        "customer_payment_title": "Paiement client",
        "supplier_payment_title": "Paiement fournisseur",
        "amount_paid": "Montant payé",
        "method": "Méthode de paiement",
        "account": "Compte banque/caisse",
        "reference": "Référence",
        "invoice": "Facture(s) concernée(s)",
        "invoice_amount": "Montant facture",
        "already_paid": "Montant déjà payé",
        "remaining_balance": "Solde restant",
        "invoice_status": "Statut facture",
        "no_invoice": "Aucune facture (crédit non affecté)",
        "order": "Commande(s) fournisseur concernée(s)",
        "order_amount": "Montant commande",
        "advance_used": "Avance utilisée",
        "no_order": "Aucune commande (avance générale)",
        "not_available": "Non applicable",
        # Global export - extra sections, Section 3, 2026-09-05
        "invoices_section": "Liste des factures",
        "payments_section": "Liste des paiements",
        "reliquat_section": "Reliquat par produit",
        "purchase_history_section": "Historique des achats",
        "payments_advances_section": "Paiements et avances",
        "trucks_section": "Camions rattachés",
        "settlements_section": "Règlements par trajet",
        "advances_section": "Avances",
        "opening_debts_section": "Dettes antérieures",
        # Per-invoice PDF (feedback 2026-09-10)
        "invoice_title": "Facture",
        "invoice_number": "Numéro de facture",
        "issued_date": "Date d'émission",
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
        "opening_debts_section": "Prior debts",
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
        "summary": "Résumé des soldes",
        "history": "Historique complet",
        "settlement_title": "Règlement par trajet",
        "trip_reference": "Référence du trajet",
        "truck": "Camion",
        "plate": "Plaque (tracteur / citerne)",
        "transporter": "Transporteur",
        "supplier": "Fournisseur",
        "client": "Client",
        "product": "Produit",
        "quantity": "Quantité chargée",
        "quantity_delivered": "Quantité livrée",
        "loss": "Perte",
        "trip_status": "Statut du trajet",
        "gross_amount": "Montant brut",
        "deductions": "Déductions",
        "net_amount": "Montant net",
        "date": "Date",
        "notes": "Notes",
        "status": "Statut",
        "proof": "Justificatif",
        "customer_payment_title": "Paiement client",
        "supplier_payment_title": "Paiement fournisseur",
        "amount_paid": "Montant payé",
        "method": "Méthode de paiement",
        "account": "Compte banque/caisse",
        "reference": "Référence",
        "invoice": "Facture(s) concernée(s)",
        "invoice_amount": "Montant facture",
        "already_paid": "Montant déjà payé",
        "remaining_balance": "Solde restant",
        "invoice_status": "Statut facture",
        "no_invoice": "Aucune facture (crédit non affecté)",
        "order": "Commande(s) fournisseur concernée(s)",
        "order_amount": "Montant commande",
        "advance_used": "Avance utilisée",
        "no_order": "Aucune commande (avance générale)",
        "not_available": "Non applicable",
        "invoices_section": "Liste des factures",
        "payments_section": "Liste des paiements",
        "reliquat_section": "Reliquat par produit",
        "purchase_history_section": "Historique des achats",
        "payments_advances_section": "Paiements et avances",
        "trucks_section": "Camions rattachés",
        "settlements_section": "Règlements par trajet",
        "advances_section": "Avances",
        "opening_debts_section": "Dettes antérieures",
        "invoice_title": "Facture",
        "invoice_number": "Numéro de facture",
        "issued_date": "Date d'émission",
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
    "label": "Libellé",
    "type": "Type",
    "date": "Date",
    "amount": "Montant",
    "reference": "Référence",
    "note": "Note",
    "notes": "Notes",
    "proof_url": "Justificatif",
    "proof": "Justificatif",
    "status": "Statut",
    "outstanding_balance": "Solde impayé",
    "total_due": "Total dû",
    "open_advances": "Avances ouvertes",
    "net_balance": "Solde net",
    "last_advance": "Dernière avance",
    "last_payment": "Dernier paiement",
    "total_purchased": "Total acheté",
    "total_paid": "Total payé",
    "total_invoiced": "Total facturé",
    "total_received": "Total encaissé",
    "open_invoices": "Factures ouvertes",
    "invoice_number": "Facture",
    "issued_date": "Date d'émission",
    "quantity_loaded": "Qté chargée",
    "delivered_quantity": "Qté reçue",
    "total_amount": "Montant total",
    "outstanding": "Solde restant",
    "payment_date": "Date de paiement",
    "method": "Méthode de paiement",
    "indirect": "Indirect",
    "is_advance": "Avance",
    "product_name": "Produit",
    "product": "Produit",
    "total_reliquat": "Reliquat",
    "purchase_date": "Date d'achat",
    "quantity_litres": "Quantité (L)",
    "unit_price": "Prix unitaire",
    "internal_id": "Camion",
    "tractor_registration": "Plaque tracteur",
    "tanker_registration": "Plaque citerne",
    "trip_reference": "Trajet",
    "base_amount": "Montant brut",
    "deduction_amount": "Déduction",
    "net_amount": "Montant net",
    "settled": "Soldé",
    "advance_applied": "Avance appliquée",
    # "Nouvelle dette" / Avances sections (2026-10-11)
    "available_credit": "Avance disponible",
    "paid_amount": "Payé",
    "remaining_amount": "Reste à payer",
    "available": "Disponible",
    "unallocated_amount": "Crédit non affecté",
    "account": "Compte",
}

# Enum/code VALUE -> printable-value translation (2026-09-05 language fix):
# the "type"/"status"/"method" COLUMNS above hold raw model choice codes
# (e.g. "PAID", "advance_given", "CASH") as their cell values, not just
# their header - _stringify() printed those verbatim regardless of lang,
# which is the other half of the English-leak bug. Same fr-only/ar-falls-
# back-to-fr policy as FIELD_LABELS_FR above.
VALUE_LABELS_FR = {
    # SupplierLedgerService/TransporterLedgerService entry "type"
    "advance_given": "Avance versée",
    "debt_created": "Dette créée",
    "advance_consumed": "Avance consommée",
    "payment": "Paiement",
    "invoice": "Facture",
    "opening_debt": "Dette antérieure",
    "advance_received": "Avance reçue",
    # Advance status (Avances sections, 2026-10-11)
    "AVAILABLE": "Disponible",
    "PARTLY_USED": "Partiellement utilisée",
    "USED": "Utilisée",
    "UNPAID": "Non payé",
    # Invoice.Status / SupplierOrder.Status / TransportPayment.Status
    # (union - no colliding meaning across these enums)
    "DRAFT": "Brouillon",
    "VALIDATED": "Validée",
    "CONFIRMED": "Confirmée",
    "PARTIALLY_PAID": "Partiellement payé",
    "PAID": "Payé",
    "CANCELLED": "Annulé",
    "PLANNED": "Planifié",
    "PAYABLE": "À payer",
    "DEDUCTION_APPLIED": "Déduction appliquée",
    # Trip.Status (frontend/src/locales/fr.json trips.status - reused
    # verbatim here so both sides of the app use the same French wording)
    "ASSIGNED": "Affecté",
    "SENT_FOR_LOADING": "Envoyé au chargement",
    "LOADING": "Chargement en cours",
    "LOADED": "Chargé",
    "ROAD_TRANSIT": "Transit routière",
    "IN_TRANSIT": "En transit",
    "BORDER": "Frontière",
    "CUSTOMS": "Douane",
    "GOING_TO_COMPANY_STOCK": "En route vers stock entreprise",
    "ARRIVED_AT_COMPANY_STOCK": "Arrivé au stock entreprise",
    "STOCKED": "Stocké",
    "GOING_TO_CLIENT": "En route vers le client",
    "ARRIVED_AT_CLIENT": "Arrivé chez le client",
    "QUANTITY_CONTROL": "Contrôle de quantité",
    "DELIVERED": "Livré",
    "COMPLETED": "Terminé",
    "BLOCKED": "Bloqué",
    # CustomerPayment.Method / SupplierPayment.Method
    "CASH": "Espèces",
    "BANK_TRANSFER": "Virement bancaire",
    "CHEQUE": "Chèque",
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
    "available_credit", "paid_amount", "remaining_amount", "available", "unallocated_amount",
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
        bottomMargin=FOOTER_MARGIN,
        title=title,
    )


# Reports-document layout for the 3 party ledgers (client request
# 2026-10-09: "même structure que le relevé client"). Field-name -> column
# kind, used for both the column width (report_pdf._KIND_WIDTH_MM) and the
# number formatting; any other field is pre-formatted (translated enum,
# Oui/Non, nested dict) and printed as text.
_DATE_FIELDS = {"date", "issued_date", "payment_date", "purchase_date", "created_at"}
_REF_FIELDS = {"reference", "invoice_number", "trip_reference", "internal_id"}
_ENUM_FIELDS = {"type", "status", "method", "indirect", "is_advance", "settled"}
_ACCOUNT_TYPE_LABELS = {
    "client": ("Client", "Client", "عميل"),
    "fournisseur": ("Fournisseur", "Supplier", "مورد"),
    "transporteur": ("Transporteur", "Transporter", "ناقل"),
}
_LEDGER_INFO_LABELS = {
    "generated_on": ("Généré le", "Generated on", "تاريخ الإنشاء"),
    "account_type": ("Type de compte", "Account type", "نوع الحساب"),
    "party": ("Compte", "Account", "الحساب"),
    "currency": ("Devise", "Currency", "العملة"),
    "empty": ("Aucune donnée.", "No data.", "لا توجد بيانات."),
}


def _ledger_column(field: str, lang: str) -> dict:
    if field in _MONEY_FIELDS:
        kind = "money"
    elif field in _QUANTITY_FIELDS:
        kind = "quantity"
    elif field in _UNIT_PRICE_FIELDS:
        kind = "unit_money"
    elif field in _DATE_FIELDS:
        kind = "date"
    elif field in _REF_FIELDS:
        kind = "ref"
    elif field in _ENUM_FIELDS:
        kind = "enum"
    else:
        kind = "text"
    numeric = kind in ("money", "quantity", "unit_money")
    return {
        "field": field,
        "label": _translate_key(field, lang),
        "kind": kind,
        "align": "end" if numeric else "start",
        "enum_labels": {},
    }


def _ledger_cell(column: dict, value, lang: str):
    """Raw value for money/quantity/unit-price/date columns (report_pdf
    formats them), display string for every other column."""
    if column["kind"] in ("money", "quantity", "unit_money", "date"):
        return value
    if value is None or value == "":
        return None
    return _format_field_value(column["field"], value, lang)


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
    """Generic party-ledger PDF: the history table (`rows`) plus any number
    of labeled sections (`extra_sections`, each `{"title", "rows"}` - each
    ledger prints every section already visible on its page), and the
    balance summary. Deliberately generic over dict shape (columns come from
    rows[0].keys(), summary lines from summary.items()) so each caller keeps
    adapting its own service's response at the call site.

    Restyle 2026-10-09: rendered through report_pdf.render_report_pdf with
    the same masthead, information grid, table look, totals block and
    "Page n / N" footer as the Reports page PDFs (e.g. Relevé client). A
    section with no rows is skipped, so export never crashes on missing
    data; a ledger with no rows at all prints the empty-table text."""
    from apps.reports.services.report_labels import LABELS as REPORT_LABELS
    from apps.reports.services.report_pdf import render_report_pdf

    lang = lang if lang in ("fr", "en", "ar") else "fr"
    index = ("fr", "en", "ar").index(lang)
    labels = _labels(lang)

    sections = [{"title": labels["history"], "rows": rows}] + list(extra_sections or [])
    sections = [section for section in sections if section["rows"]] or [{"title": labels["history"], "rows": []}]

    tables, document_rows = [], []
    for number, section in enumerate(sections):
        key = f"s{number}"
        fields = list(section["rows"][0].keys()) if section["rows"] else ["date", "type", "reference", "amount"]
        # Date first, like every accounting statement.
        fields.sort(key=lambda field: field not in _DATE_FIELDS)
        columns = [_ledger_column(field, lang) for field in fields]
        tables.append({"title": section["title"], "columns": columns, "section": key})
        for row in section["rows"]:
            cells = {column["field"]: _ledger_cell(column, row.get(column["field"]), lang) for column in columns}
            document_rows.append({**cells, "section": key})

    summary_lines = []
    for key, value in summary.items():
        if key in ("id", "label"):  # the party is already in the title / info grid
            continue
        money = key in _MONEY_FIELDS or (key in ("last_payment", "last_advance") and isinstance(value, Decimal))
        summary_lines.append(
            {
                "label": _translate_key(key, lang),
                "value": value if money else (_format_field_value(key, value, lang) or "—"),
                "kind": "money" if money and value is not None else "text",
                "emphasis": key in _FINAL_BALANCE_KEYS,
            }
        )

    info_label = {key: values[index] for key, values in _LEDGER_INFO_LABELS.items()}
    account_label = _ACCOUNT_TYPE_LABELS.get(account_type, (account_type,) * 3)[index]
    document = {
        "company": {"name": company_name},
        "title": f"{labels['title']} — {party_name}",
        "lang": lang,
        "direction": "rtl" if lang == "ar" else "ltr",
        "orientation": "portrait",
        "info": [
            {"label": info_label["generated_on"], "value": export_date.strftime("%d/%m/%Y")},
            {"label": info_label["account_type"], "value": account_label},
            {"label": info_label["party"], "value": party_name},
            {"label": info_label["currency"], "value": "XOF"},
        ],
        "tables": tables,
        "opening_balance": None,
        "summary": summary_lines,
        "labels": {"page": REPORT_LABELS[lang]["ui.page"]},
        "empty_text": info_label["empty"],
    }
    return render_report_pdf(document, document_rows, lang)


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
    doc.build(elements, canvasmaker=numbered_canvas_cls(running_title=f"{DEFAULT_COMPANY_NAME} — {title}", lang=lang, side_margin=15 * mm))
    return buffer.getvalue()


def render_trip_settlement_pdf(payment, lang: str = "fr") -> bytes:
    """Per-trip settlement PDF, restyled 2026-10-11 in the Reports document
    layout - see payment_pdf.py."""
    from apps.reports.services.payment_pdf import render_trip_settlement_pdf as render

    return render(payment, lang)


def render_invoice_pdf(invoice, lang: str = "fr") -> bytes:
    """Per-invoice PDF (feedback 2026-09-10), restyled 2026-10-09 in the
    Reports document layout - see invoice_pdf.py."""
    from apps.reports.services.invoice_pdf import render_invoice_pdf as render

    return render(invoice, lang)


def render_customer_payment_pdf(payment, lang: str = "fr") -> bytes:
    """Per-receipt PDF (payment or advance), restyled 2026-10-11 in the
    Reports document layout - see payment_pdf.py."""
    from apps.reports.services.payment_pdf import render_customer_payment_pdf as render

    return render(payment, lang)


def render_supplier_payment_pdf(payment, lang: str = "fr") -> bytes:
    """Per-payment PDF, restyled 2026-10-11 in the Reports document layout -
    see payment_pdf.py."""
    from apps.reports.services.payment_pdf import render_supplier_payment_pdf as render

    return render(payment, lang)


# --- Sections shared by the 3 party-ledger PDFs (2026-10-11) ----------------


def opening_debt_section_rows(debts) -> list[dict]:
    """"Dettes antérieures" rows, same columns as the ledger page."""
    from apps.finance.services import OpeningDebtService

    rows = []
    for debt in debts:
        line = OpeningDebtService.describe(debt)
        rows.append({
            "date": debt.date,
            "reference": debt.reference or None,
            "amount": debt.amount,
            "paid_amount": line["paid_amount"],
            "remaining_amount": line["remaining_amount"],
            "status": line["status"],
            "notes": debt.notes or None,
        })
    return rows


def advance_status(amount, available, *, reversed_=False) -> str:
    """Same wording as the ledger page's Avances section (AdvancesCard)."""
    if reversed_:
        return "CANCELLED"
    if available <= 0:
        return "USED"
    return "PARTLY_USED" if available < amount else "AVAILABLE"


def advance_section_rows(items) -> list[dict]:
    """"Avances" rows from (date, reference, account, amount, available,
    reversed) tuples - each ledger maps its own advance model to them."""
    return [
        {
            "date": date,
            "reference": reference or None,
            "account": account or None,
            "amount": amount,
            "available": Decimal("0.00") if reversed_ else available,
            "status": advance_status(amount, available, reversed_=reversed_),
        }
        for date, reference, account, amount, available, reversed_ in items
    ]
