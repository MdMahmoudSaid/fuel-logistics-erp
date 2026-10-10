# Client invoice PDF in the Reports document style (client request
# 2026-10-09: "même structure que le relevé client"). Builds a report
# `document` and hands it to report_pdf.render_report_pdf, so the invoice gets
# exactly the same masthead (logo + AZUR ÉNERGIE), information grid, table,
# totals block and "Page n / N" footer as every Reports page PDF. Prints every
# field of the previous label/value invoice PDF (number, client, product,
# trip, truck, plates, loaded/delivered quantity, unit price, total, status,
# issue date, export date) plus what is already paid and what remains.

import datetime

from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME
from apps.reports.services.report_labels import LABELS as REPORT_LABELS

_LANGS = ("fr", "en", "ar")

_TEXT = {
    "title": ("Facture", "Invoice", "فاتورة"),
    "invoice_number": ("Facture n°", "Invoice no.", "رقم الفاتورة"),
    "issued_date": ("Date d'émission", "Issue date", "تاريخ الإصدار"),
    "client": ("Client", "Client", "العميل"),
    "status": ("Statut", "Status", "الحالة"),
    "phone": ("Téléphone", "Phone", "الهاتف"),
    "address": ("Adresse", "Address", "العنوان"),
    "export_date": ("Date d'export", "Export date", "تاريخ التصدير"),
    "currency": ("Devise", "Currency", "العملة"),
    "lines": ("Détail de la livraison", "Delivery details", "تفاصيل التسليم"),
    "trip": ("Trajet", "Trip", "الرحلة"),
    "truck": ("Camion (tracteur / citerne)", "Truck (tractor / tanker)", "الشاحنة (الجرار / الصهريج)"),
    "product": ("Produit", "Product", "المنتج"),
    "quantity_loaded": ("Qté chargée", "Loaded qty", "الكمية المحمّلة"),
    "quantity_delivered": ("Qté livrée", "Delivered qty", "الكمية المسلّمة"),
    "unit_price": ("Prix unitaire", "Unit price", "سعر الوحدة"),
    "amount": ("Montant", "Amount", "المبلغ"),
    "total": ("Total facture", "Invoice total", "إجمالي الفاتورة"),
    "paid": ("Déjà payé", "Already paid", "المدفوع"),
    "remaining": ("Reste à payer", "Remaining due", "المتبقي للدفع"),
    "empty": ("Aucune ligne.", "No line.", "لا توجد بنود."),
}

_STATUS = {
    "DRAFT": ("Brouillon", "Draft", "مسودة"),
    "VALIDATED": ("Validée", "Validated", "مصادق عليها"),
    "PARTIALLY_PAID": ("Partiellement payée", "Partially paid", "مدفوعة جزئيًا"),
    "PAID": ("Payée", "Paid", "مدفوعة"),
    "CANCELLED": ("Annulée", "Cancelled", "ملغاة"),
}


def _t(key: str, lang: str) -> str:
    return _TEXT[key][_LANGS.index(lang)]


def _date(value) -> str:
    if isinstance(value, str):
        value = datetime.date.fromisoformat(value[:10])
    return value.strftime("%d/%m/%Y") if value else ""


def build_invoice_document(invoice, lang: str = "fr") -> tuple[dict, list[dict]]:
    """(document, rows) for report_pdf.render_report_pdf."""
    from apps.finance.services import PaymentAllocationService

    lang = lang if lang in _LANGS else "fr"
    sales = invoice.all_sales
    customer = sales[0].customer
    currency = sales[0].currency or "XOF"
    outstanding = PaymentAllocationService.get_invoice_outstanding(invoice)

    info = [
        {"label": _t("invoice_number", lang), "value": invoice.invoice_number},
        {"label": _t("issued_date", lang), "value": _date(invoice.issued_date)},
        {"label": _t("client", lang), "value": customer.name},
        {"label": _t("status", lang), "value": _STATUS.get(invoice.status, (invoice.status,) * 3)[_LANGS.index(lang)]},
    ]
    if customer.phone:
        info.append({"label": _t("phone", lang), "value": customer.phone})
    if customer.address:
        info.append({"label": _t("address", lang), "value": customer.address})
    info += [
        {"label": _t("export_date", lang), "value": _date(datetime.date.today())},
        {"label": _t("currency", lang), "value": currency},
    ]

    def column(field, kind, align="start"):
        return {"field": field, "label": _t(field, lang), "kind": kind, "align": align}

    columns = [
        column("trip", "ref"),
        column("truck", "text"),
        column("product", "text"),
        column("quantity_loaded", "quantity", "end"),
        column("quantity_delivered", "quantity", "end"),
        column("unit_price", "unit_money", "end"),
        column("amount", "money", "end"),
    ]
    rows = [
        {
            "trip": sale.trip.reference,
            "truck": (
                f"{sale.trip.truck.internal_id} "
                f"({sale.trip.truck.tractor_registration} / {sale.trip.truck.tanker_registration})"
            ),
            "product": sale.product.name,
            "quantity_loaded": sale.trip.quantity_loaded,
            "quantity_delivered": sale.delivered_quantity,
            "unit_price": sale.unit_selling_price,
            "amount": sale.subtotal,
        }
        for sale in sales
    ]

    summary = [
        {"label": _t("total", lang), "value": invoice.total_amount, "kind": "money", "emphasis": False},
        {"label": _t("paid", lang), "value": invoice.total_amount - outstanding, "kind": "money", "emphasis": False},
        {"label": _t("remaining", lang), "value": outstanding, "kind": "money", "emphasis": True},
    ]

    document = {
        "company": {"name": DEFAULT_COMPANY_NAME},
        "title": f"{_t('title', lang)} {invoice.invoice_number}",
        "lang": lang,
        "direction": "rtl" if lang == "ar" else "ltr",
        "orientation": "portrait",
        "info": info,
        "tables": [{"title": _t("lines", lang), "columns": columns}],
        "opening_balance": None,
        "summary": summary,
        "labels": {"page": REPORT_LABELS[lang]["ui.page"]},
        "empty_text": _t("empty", lang),
    }
    return document, rows


def render_invoice_pdf(invoice, lang: str = "fr") -> bytes:
    from apps.reports.services.report_pdf import render_report_pdf

    document, rows = build_invoice_document(invoice, lang)
    return render_report_pdf(document, rows, document["lang"])
