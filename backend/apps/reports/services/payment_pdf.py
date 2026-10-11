# Payment / advance PDFs in the Reports document style (client request
# 2026-10-11: "le PDF de paiement est très ancien ... améliorer aussi le UI
# des paiements et des avances"). Same approach as invoice_pdf.py: each
# builder returns a report `document` + rows for report_pdf.render_report_pdf,
# so every per-record PDF gets the masthead (logo + AZUR ÉNERGIE), the
# information grid, a detail table, the totals block and the "Page n / N"
# footer of the Reports PDFs. Every field of the previous label/value PDFs is
# still printed.

import datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME
from apps.reports.services.report_labels import LABELS as REPORT_LABELS

_LANGS = ("fr", "en", "ar")
ZERO = Decimal("0.00")

_TEXT = {
    "customer_payment": ("Paiement client", "Customer payment", "دفعة عميل"),
    "customer_advance": ("Avance client", "Customer advance", "سلفة عميل"),
    "supplier_payment": ("Paiement fournisseur", "Supplier payment", "دفعة مورد"),
    "supplier_advance": ("Avance fournisseur", "Supplier advance", "سلفة مورد"),
    "transporter_advance": ("Avance transporteur", "Transporter advance", "سلفة ناقل"),
    "settlement": ("Règlement par trajet", "Trip settlement", "تسوية الرحلة"),
    "client": ("Client", "Client", "العميل"),
    "supplier": ("Fournisseur", "Supplier", "المورد"),
    "transporter": ("Transporteur", "Transporter", "الناقل"),
    "date": ("Date", "Date", "التاريخ"),
    "amount": ("Montant", "Amount", "المبلغ"),
    "method": ("Méthode", "Method", "الطريقة"),
    "account": ("Compte", "Account", "الحساب"),
    "reference": ("Référence", "Reference", "المرجع"),
    "status": ("Statut", "Status", "الحالة"),
    "notes": ("Notes", "Notes", "ملاحظات"),
    "export_date": ("Date d'export", "Export date", "تاريخ التصدير"),
    "currency": ("Devise", "Currency", "العملة"),
    "proof": ("Justificatif", "Proof", "المستند"),
    "attached": ("Joint", "Attached", "مرفق"),
    "none": ("Aucun", "None", "لا يوجد"),
    "active": ("Valide", "Valid", "صالح"),
    "cancelled": ("Annulé", "Cancelled", "ملغى"),
    "allocation": ("Répartition du paiement", "Payment allocation", "توزيع الدفعة"),
    "target": ("Affecté à", "Applied to", "مخصص لـ"),
    "debt_amount": ("Montant de la dette", "Debt amount", "مبلغ الدين"),
    "applied": ("Payé par ce paiement", "Paid by this payment", "المدفوع بهذه الدفعة"),
    "remaining": ("Reste à payer", "Remaining due", "المتبقي للدفع"),
    "invoice": ("Facture", "Invoice", "فاتورة"),
    "opening_debt": ("Dette antérieure", "Prior debt", "دين سابق"),
    "open_credit": ("Avance disponible", "Available advance", "سلفة متاحة"),
    "received": ("Montant reçu", "Amount received", "المبلغ المستلم"),
    "allocated_total": ("Affecté aux dettes", "Applied to debts", "المخصص للديون"),
    "paid": ("Montant payé", "Amount paid", "المبلغ المدفوع"),
    "order": ("Commande", "Order", "الطلب"),
    "order_or_debt": ("Commande / dette", "Order / debt", "الطلب / الدين"),
    "product": ("Produit", "Product", "المنتج"),
    "quantity": ("Quantité", "Quantity", "الكمية"),
    "advance_used": ("Avance utilisée", "Advance used", "السلفة المستخدمة"),
    "settled_debt": ("Dette réglée", "Settled debt", "الدين المسدد"),
    "consumption": ("Utilisation de l'avance", "Use of the advance", "استخدام السلفة"),
    "debt": ("Dette couverte", "Debt covered", "الدين المغطى"),
    "consumed": ("Montant utilisé", "Amount used", "المبلغ المستخدم"),
    "advance_amount": ("Montant de l'avance", "Advance amount", "مبلغ السلفة"),
    "consumed_total": ("Déjà utilisé", "Already used", "المستخدم"),
    "available": ("Reste disponible", "Still available", "المتبقي المتاح"),
    "trip": ("Trajet", "Trip", "الرحلة"),
    "truck": ("Camion (tracteur / citerne)", "Truck (tractor / tanker)", "الشاحنة (الجرار / الصهريج)"),
    "quantity_loaded": ("Qté chargée", "Loaded qty", "الكمية المحمّلة"),
    "quantity_delivered": ("Qté livrée", "Delivered qty", "الكمية المسلّمة"),
    "loss": ("Perte", "Loss", "الفاقد"),
    "trip_status": ("Statut du trajet", "Trip status", "حالة الرحلة"),
    "payments": ("Paiements effectués", "Payments made", "الدفعات المنفذة"),
    "gross_amount": ("Montant brut", "Gross amount", "المبلغ الإجمالي"),
    "deductions": ("Déductions", "Deductions", "الخصومات"),
    "net_amount": ("Montant net", "Net amount", "المبلغ الصافي"),
    "settled": ("Déjà payé", "Already paid", "المدفوع"),
    "empty": ("Aucune ligne.", "No line.", "لا توجد بنود."),
}

_METHOD = {
    "CASH": ("Espèces", "Cash", "نقدًا"),
    "BANK_TRANSFER": ("Virement bancaire", "Bank transfer", "تحويل بنكي"),
    "CHEQUE": ("Chèque", "Cheque", "شيك"),
    "OTHER": ("Autre", "Other", "أخرى"),
}

_STATUS = {
    "DRAFT": ("Brouillon", "Draft", "مسودة"),
    "VALIDATED": ("Validée", "Validated", "مصادق عليها"),
    "CONFIRMED": ("Confirmée", "Confirmed", "مؤكدة"),
    "PARTIALLY_PAID": ("Partiellement payé", "Partially paid", "مدفوع جزئيًا"),
    "PAID": ("Payé", "Paid", "مدفوع"),
    "CANCELLED": ("Annulé", "Cancelled", "ملغى"),
    "PLANNED": ("Planifié", "Planned", "مخطط"),
    "PAYABLE": ("À payer", "Payable", "مستحق الدفع"),
    "DEDUCTION_APPLIED": ("Déduction appliquée", "Deduction applied", "تم تطبيق الخصم"),
}


def _lang(lang):
    return lang if lang in _LANGS else "fr"


def _t(key, lang):
    return _TEXT[key][_LANGS.index(lang)]


def _enum(table, value, lang):
    return table.get(value, (value,) * 3)[_LANGS.index(lang)] if value else ""


def _date(value):
    if isinstance(value, str) and value:
        value = datetime.date.fromisoformat(value[:10])
    if isinstance(value, datetime.datetime):
        value = (timezone.localtime(value) if timezone.is_aware(value) else value).date()
    return value.strftime("%d/%m/%Y") if value else ""


def _account(obj):
    account = obj.bank_account if obj.bank_account_id else obj.cash_account
    return account.name if account else ""


def _info(lang, *pairs):
    """Information grid rows, skipping empty optional values."""
    return [{"label": _t(key, lang), "value": value} for key, value in pairs if value not in (None, "")]


def _column(field, label, kind, align="start"):
    return {"field": field, "label": label, "kind": kind, "align": align}


def _money_line(label, value, emphasis=False):
    return {"label": label, "value": value, "kind": "money", "emphasis": emphasis}


def _document(lang, title, info, tables, summary):
    return {
        "company": {"name": DEFAULT_COMPANY_NAME},
        "title": title,
        "lang": lang,
        "direction": "rtl" if lang == "ar" else "ltr",
        "orientation": "portrait",
        "info": info,
        "tables": tables,
        "opening_balance": None,
        "summary": summary,
        "labels": {"page": REPORT_LABELS[lang]["ui.page"]},
        "empty_text": _t("empty", lang),
    }


def _render(document, rows):
    from apps.reports.services.report_pdf import render_report_pdf

    return render_report_pdf(document, rows, document["lang"])


# --- customer payment / advance -------------------------------------------


def build_customer_payment_document(payment, lang="fr"):
    from apps.finance.services import OpeningDebtService, PaymentAllocationService

    lang = _lang(lang)
    title = _t("customer_advance" if payment.is_advance else "customer_payment", lang)
    info = _info(
        lang,
        ("client", payment.customer.name),
        ("date", _date(payment.payment_date)),
        ("method", _enum(_METHOD, payment.method, lang)),
        ("account", _account(payment)),
        ("reference", payment.reference or f"PAY-{payment.id}"),
        ("status", _t("cancelled" if payment.is_reversed else "active", lang)),
        ("export_date", _date(datetime.date.today())),
        ("currency", "XOF"),
        ("notes", payment.note),
    )

    rows = []
    for allocation in payment.allocations.select_related("invoice", "opening_debt").order_by("created_at", "id"):
        if allocation.invoice_id:
            invoice = allocation.invoice
            rows.append({
                "target": f"{_t('invoice', lang)} {invoice.invoice_number}",
                "date": invoice.issued_date,
                "debt_amount": invoice.total_amount,
                "applied": allocation.amount,
                "remaining": PaymentAllocationService.get_invoice_outstanding(invoice),
            })
        elif allocation.opening_debt_id:
            debt = allocation.opening_debt
            rows.append({
                "target": f"{_t('opening_debt', lang)} {debt.reference}".strip(),
                "date": debt.date,
                "debt_amount": debt.amount,
                "applied": allocation.amount,
                "remaining": OpeningDebtService.remaining_amount(debt),
            })
    allocated = sum((row["applied"] for row in rows), ZERO)
    open_credit = ZERO if payment.is_reversed else PaymentAllocationService.get_payment_unallocated_amount(payment)
    if open_credit > ZERO:
        rows.append({"target": _t("open_credit", lang), "date": None, "debt_amount": None,
                     "applied": open_credit, "remaining": None})

    columns = [
        _column("target", _t("target", lang), "text"),
        _column("date", _t("date", lang), "date"),
        _column("debt_amount", _t("debt_amount", lang), "money", "end"),
        _column("applied", _t("applied", lang), "money", "end"),
        _column("remaining", _t("remaining", lang), "money", "end"),
    ]
    # The figure that matters: what is still available on an advance, what
    # came in on an ordinary payment.
    summary = [
        _money_line(_t("received", lang), payment.amount, emphasis=not payment.is_advance),
        _money_line(_t("allocated_total", lang), allocated),
        _money_line(_t("open_credit", lang), open_credit, emphasis=payment.is_advance),
    ]
    document = _document(
        lang, f"{title} — {payment.customer.name}", info,
        [{"title": _t("allocation", lang), "columns": columns}], summary,
    )
    return document, rows


def render_customer_payment_pdf(payment, lang="fr") -> bytes:
    return _render(*build_customer_payment_document(payment, lang))


# --- supplier payment ------------------------------------------------------


def build_supplier_payment_document(payment, lang="fr"):
    from apps.finance.models import AdvanceConsumption
    from apps.finance.services import ControlledDebtPaymentService, OpeningDebtService

    lang = _lang(lang)
    info = _info(
        lang,
        ("supplier", payment.supplier.name),
        ("date", _date(payment.payment_date)),
        ("method", _enum(_METHOD, payment.method, lang)),
        ("account", _account(payment)),
        ("reference", payment.reference or f"PAY-{payment.id}"),
        ("status", _t("cancelled" if payment.is_reversed else "active", lang)),
        ("export_date", _date(datetime.date.today())),
        ("currency", "XOF"),
    )

    rows = []
    if payment.supplier_order_id:
        order = payment.supplier_order
        advance_used = (
            AdvanceConsumption.objects.filter(
                debt_content_type=ContentType.objects.get_for_model(type(order)),
                debt_object_id=order.id,
                reversed_at__isnull=True,
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        rows.append({
            "debt": order.reference,
            "product": order.product.name,
            "quantity": order.quantity_litres,
            "debt_amount": order.total_amount,
            "advance_used": advance_used,
            "remaining": ControlledDebtPaymentService.describe_supplier_order(order)["remaining_amount"],
            "status": order.status,
        })
    elif payment.opening_debt_id:
        debt = payment.opening_debt
        rows.append({
            "debt": f"{_t('opening_debt', lang)} {debt.reference}".strip(),
            "product": None,
            "quantity": None,
            "debt_amount": debt.amount,
            "advance_used": OpeningDebtService.paid_amount(debt) - OpeningDebtService.cash_paid(debt),
            "remaining": OpeningDebtService.remaining_amount(debt),
            "status": OpeningDebtService.describe(debt)["status"],
        })

    columns = [
        _column("debt", _t("order_or_debt", lang), "ref"),
        _column("product", _t("product", lang), "text"),
        _column("quantity", _t("quantity", lang), "quantity", "end"),
        _column("debt_amount", _t("debt_amount", lang), "money", "end"),
        _column("advance_used", _t("advance_used", lang), "money", "end"),
        _column("remaining", _t("remaining", lang), "money", "end"),
        {**_column("status", _t("status", lang), "status"),
         "enum_labels": {key: value[_LANGS.index(lang)] for key, value in _STATUS.items()}},
    ]
    summary = [_money_line(_t("paid", lang), payment.amount, emphasis=True)]
    document = _document(
        lang, f"{_t('supplier_payment', lang)} — {payment.supplier.name}", info,
        [{"title": _t("settled_debt", lang), "columns": columns}], summary,
    )
    return document, rows


def render_supplier_payment_pdf(payment, lang="fr") -> bytes:
    return _render(*build_supplier_payment_document(payment, lang))


# --- supplier / transporter advance ---------------------------------------


def _debt_label(debt, lang):
    from apps.finance.models import OpeningDebt, TransportPayment

    if isinstance(debt, OpeningDebt):
        return f"{_t('opening_debt', lang)} {debt.reference}".strip(), debt.date
    if isinstance(debt, TransportPayment):
        return f"{_t('trip', lang)} {debt.trip.reference}", debt.created_at
    return f"{_t('order', lang)} {debt.reference}", debt.purchase_date


def build_advance_document(advance, lang="fr"):
    from apps.finance.models import SupplierAdvance

    lang = _lang(lang)
    is_supplier = isinstance(advance, SupplierAdvance)
    party = advance.supplier if is_supplier else advance.transporter
    info = _info(
        lang,
        ("supplier" if is_supplier else "transporter", party.name),
        ("date", _date(advance.date)),
        ("account", _account(advance)),
        ("reference", advance.reference),
        ("proof", _t("attached" if advance.document_id else "none", lang)),
        ("export_date", _date(datetime.date.today())),
        ("currency", "XOF"),
        ("notes", advance.notes),
    )

    rows = []
    for consumption in advance.consumptions.filter(reversed_at__isnull=True).order_by("created_at", "id"):
        label, date = _debt_label(consumption.debt_object, lang)
        rows.append({"date": date, "debt": label, "consumed": consumption.amount})
    consumed = sum((row["consumed"] for row in rows), ZERO)

    columns = [
        _column("date", _t("date", lang), "date"),
        _column("debt", _t("debt", lang), "text"),
        _column("consumed", _t("consumed", lang), "money", "end"),
    ]
    summary = [
        _money_line(_t("advance_amount", lang), advance.amount),
        _money_line(_t("consumed_total", lang), consumed),
        _money_line(_t("available", lang), advance.amount - consumed, emphasis=True),
    ]
    title = _t("supplier_advance" if is_supplier else "transporter_advance", lang)
    document = _document(
        lang, f"{title} — {party.name}", info,
        [{"title": _t("consumption", lang), "columns": columns}], summary,
    )
    return document, rows


def render_advance_pdf(advance, lang="fr") -> bytes:
    return _render(*build_advance_document(advance, lang))


# --- transporter trip settlement ------------------------------------------


def build_trip_settlement_document(payment, lang="fr"):
    from apps.finance.models import TreasuryTransaction
    from apps.finance.services import AdvanceConsumptionService, ControlledDebtPaymentService

    lang = _lang(lang)
    trip = payment.trip
    truck = trip.truck
    if trip.client_id:
        client_name = trip.client.name
    elif trip.customer_order_id:
        client_name = trip.customer_order.customer.name
    else:
        client_name = ""
    delivery_control = getattr(trip, "delivery_control", None)

    from apps.reports.services.ledger_pdf import _format_quantity

    txns = list(
        TreasuryTransaction.objects.filter(
            source_content_type=ContentType.objects.get_for_model(type(payment)),
            source_object_id=payment.id,
            type=TreasuryTransaction.Type.MONEY_OUT,
        )
        .select_related("bank_account", "cash_account", "document")
        .order_by("date", "id")
    )
    has_proof = any(txn.document_id for txn in txns)
    info = _info(
        lang,
        ("trip", trip.reference),
        ("transporter", payment.transporter.name),
        ("truck", f"{truck.internal_id} ({truck.tractor_registration} / {truck.tanker_registration})"),
        ("supplier", trip.supplier.name if trip.supplier_id else ""),
        ("client", client_name),
        ("product", trip.product.name),
        ("quantity_loaded", _format_quantity(trip.quantity_loaded)),
        ("quantity_delivered",
         _format_quantity(delivery_control.received_quantity) if delivery_control else ""),
        ("loss", _format_quantity(delivery_control.loss_quantity) if delivery_control else ""),
        ("trip_status", _enum(_TRIP_STATUS, trip.status, lang)),
        ("status", _enum(_STATUS, payment.status, lang)),
        ("date", _date(payment.created_at)),
        ("proof", _t("attached" if has_proof else "none", lang)),
        ("export_date", _date(datetime.date.today())),
        ("currency", "XOF"),
        ("notes", trip.notes),
    )

    rows = [
        {"date": txn.date, "reference": txn.reference or None, "account": _account(txn), "amount": txn.amount}
        for txn in txns
    ]
    paid = ControlledDebtPaymentService._paid_for_source(type(payment), payment.id)
    advance = AdvanceConsumptionService.get_consumed_amount(payment)
    columns = [
        _column("date", _t("date", lang), "date"),
        _column("reference", _t("reference", lang), "ref"),
        _column("account", _t("account", lang), "text"),
        _column("amount", _t("amount", lang), "money", "end"),
    ]
    summary = [
        _money_line(_t("gross_amount", lang), payment.base_amount),
        _money_line(_t("deductions", lang), payment.deduction_amount),
        _money_line(_t("advance_used", lang), advance),
        _money_line(_t("net_amount", lang), payment.net_amount),
        _money_line(_t("settled", lang), paid),
        _money_line(_t("remaining", lang), payment.net_amount - paid, emphasis=True),
    ]
    document = _document(
        lang, f"{_t('settlement', lang)} — {trip.reference}", info,
        [{"title": _t("payments", lang), "columns": columns}], summary,
    )
    return document, rows


def render_trip_settlement_pdf(payment, lang="fr") -> bytes:
    return _render(*build_trip_settlement_document(payment, lang))


_TRIP_STATUS = {
    "ASSIGNED": ("Affecté", "Assigned", "مُسنَد"),
    "SENT_FOR_LOADING": ("Envoyé au chargement", "Sent for loading", "أُرسل للتحميل"),
    "LOADING": ("Chargement en cours", "Loading", "التحميل جارٍ"),
    "LOADED": ("Chargé", "Loaded", "محمَّل"),
    "ROAD_TRANSIT": ("Transit routière", "Road transit", "عبور بري"),
    "IN_TRANSIT": ("En transit", "In transit", "في الطريق"),
    "BORDER": ("Frontière", "Border", "الحدود"),
    "CUSTOMS": ("Douane", "Customs", "الجمارك"),
    "GOING_TO_COMPANY_STOCK": ("En route vers stock entreprise", "Going to company stock", "في الطريق إلى مخزون الشركة"),
    "ARRIVED_AT_COMPANY_STOCK": ("Arrivé au stock entreprise", "Arrived at company stock", "وصل إلى مخزون الشركة"),
    "STOCKED": ("Stocké", "Stocked", "مخزّن"),
    "GOING_TO_CLIENT": ("En route vers le client", "Going to client", "في الطريق إلى العميل"),
    "ARRIVED_AT_CLIENT": ("Arrivé chez le client", "Arrived at client", "وصل إلى العميل"),
    "QUANTITY_CONTROL": ("Contrôle de quantité", "Quantity control", "مراقبة الكمية"),
    "DELIVERED": ("Livré", "Delivered", "مسلَّم"),
    "COMPLETED": ("Terminé", "Completed", "مكتمل"),
    "BLOCKED": ("Bloqué", "Blocked", "محظور"),
    "CANCELLED": ("Annulé", "Cancelled", "ملغى"),
}
