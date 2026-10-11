# Priced document PDFs - the proforma (ex "offre commerciale") and, through
# build_priced_document(), the supplier purchase order (spec 2026-10-11
# documents-commerciaux §3 and §6). Inspired by the client's Vivo Energy
# proforma: billed party + document info, priced lines, "Total à payer",
# amount in words, payment terms, bank accounts. Rendered by the shared
# report_pdf engine (fr / en / ar, right-to-left for Arabic).

import datetime

from apps.reports.services.amount_words import amount_in_words
from apps.reports.services.report_labels import LABELS as REPORT_LABELS

LANGS = ("fr", "en", "ar")

TEXT = {
    "proforma": ("Facture proforma", "Proforma invoice", "فاتورة شكلية"),
    "order": ("Bon de commande", "Purchase order", "أمر شراء"),
    "number": ("N°", "No.", "رقم"),
    "billed_to": ("Client facturé", "Billed to", "العميل"),
    "supplier": ("Fournisseur", "Supplier", "المورد"),
    "address": ("Adresse", "Address", "العنوان"),
    "phone": ("Téléphone", "Phone", "الهاتف"),
    "date": ("Date", "Date", "التاريخ"),
    "due": ("Échéance", "Due", "الاستحقاق"),
    "cash": ("Comptant", "Cash", "نقدًا"),
    "validity": ("Validité", "Valid until", "صالحة حتى"),
    "currency": ("Monnaie", "Currency", "العملة"),
    "delivery_place": ("Lieu de livraison", "Delivery place", "مكان التسليم"),
    "delivery_date": ("Livraison souhaitée", "Requested delivery", "تاريخ التسليم المطلوب"),
    "lines": ("Détail", "Details", "التفاصيل"),
    "designation": ("Libellé", "Description", "البيان"),
    "quantity": ("Quantité", "Quantity", "الكمية"),
    "unit": ("Unité", "Unit", "الوحدة"),
    "unit_price": ("Prix unitaire", "Unit price", "سعر الوحدة"),
    "amount": ("Montant", "Amount", "المبلغ"),
    "total_to_pay": ("Total à payer", "Total to pay", "المجموع المستحق"),
    "total": ("Total", "Total", "المجموع"),
    "in_words": ("Arrêté à la somme de", "Amount in words", "أوقف هذا المبلغ على"),
    "terms": ("Conditions de paiement", "Payment terms", "شروط الدفع"),
    "notes": ("Commentaires", "Comments", "ملاحظات"),
    "banks": ("Comptes bancaires", "Bank accounts", "الحسابات البنكية"),
    "bank": ("Banque", "Bank", "البنك"),
    "swift": ("Code SWIFT", "SWIFT code", "رمز سويفت"),
    "account": ("Numéro de compte", "Account number", "رقم الحساب"),
    "for_company": ("Pour l'entreprise", "For the company", "عن الشركة"),
    "empty": ("Aucune ligne.", "No line.", "لا توجد سطور."),
}


def t(key: str, lang: str) -> str:
    return TEXT[key][LANGS.index(lang)]


def fmt_date(value) -> str:
    if isinstance(value, str):
        value = datetime.date.fromisoformat(value[:10])
    return value.strftime("%d/%m/%Y") if value else ""


def base_document(*, title: str, lang: str, info: list, tables: list, summary: list, blocks: list,
                  signatures: list, orientation: str = "portrait") -> dict:
    """The report_pdf document dict shared by every commercial document."""
    from apps.core.models import CompanyProfile

    return {
        "company": CompanyProfile.load().pdf_company(),
        "title": title,
        "lang": lang,
        "direction": "rtl" if lang == "ar" else "ltr",
        "orientation": orientation,
        "info": [item for item in info if item["value"]],
        "tables": tables,
        "opening_balance": None,
        "summary": summary,
        "blocks": blocks,
        "signatures": signatures,
        "labels": {"page": REPORT_LABELS[lang]["ui.page"]},
        "empty_text": t("empty", lang),
    }


def column(field: str, label: str, kind: str, align: str = "start") -> dict:
    return {"field": field, "label": label, "kind": kind, "align": align}


def build_priced_document(*, title, party_label, party, info, lines, total, currency, payment_terms,
                          notes, lang, banks, signatures) -> tuple[dict, list[dict]]:
    """(document, rows) for a priced document. `party` = {"name", "address",
    "phone"}; `lines` = [{"designation", "quantity", "unit", "unit_price",
    "amount"}]; `banks` prints the company's bank accounts."""
    from apps.core.models import CompanyProfile

    lang = lang if lang in LANGS else "fr"
    head = [
        {"label": party_label, "value": party.get("name") or ""},
        {"label": t("address", lang), "value": party.get("address") or ""},
        {"label": t("phone", lang), "value": party.get("phone") or ""},
    ]
    tables = [{
        "title": t("lines", lang), "section": "lines",
        "columns": [
            column("designation", t("designation", lang), "text"),
            column("quantity", t("quantity", lang), "number", "end"),
            column("unit", t("unit", lang), "text"),
            column("unit_price", t("unit_price", lang), "number", "end"),
            {**column("amount", t("amount", lang), "money", "end"), "currency": currency},
        ],
    }]
    rows = [{"section": "lines", **line} for line in lines]
    bank_rows = CompanyProfile.load().pdf_company()["banks"] if banks else []
    if bank_rows:
        tables.append({
            "title": t("banks", lang), "section": "banks",
            "columns": [column("bank", t("bank", lang), "text"), column("swift", t("swift", lang), "text"),
                        column("account", t("account", lang), "text")],
        })
        rows += [{"section": "banks", **bank} for bank in bank_rows]
    blocks = [{"title": t("in_words", lang), "text": amount_in_words(total, lang, currency), "boxed": True}]
    if payment_terms:
        blocks.append({"title": t("terms", lang), "text": payment_terms})
    if notes:
        blocks.append({"title": t("notes", lang), "text": notes})
    document = base_document(
        title=title, lang=lang, info=head + info, tables=tables,
        summary=[{"label": t("total_to_pay", lang), "value": total, "kind": "money", "emphasis": True,
                  "currency": currency}],
        blocks=blocks, signatures=signatures,
    )
    return document, rows


def build_proforma_document(quotation, lang: str = "fr") -> tuple[dict, list[dict]]:
    lang = lang if lang in LANGS else "fr"
    customer = quotation.customer
    party = {
        "name": quotation.customer_display_name,
        "address": customer.address if customer else "",
        "phone": customer.phone if customer else "",
    }
    info = [
        {"label": t("date", lang), "value": fmt_date(quotation.issue_date)},
        {"label": t("validity", lang) if quotation.validity_date else t("due", lang),
         "value": fmt_date(quotation.validity_date) if quotation.validity_date else t("cash", lang)},
        {"label": t("currency", lang), "value": quotation.currency},
    ]
    lines = [
        {
            "designation": line.description or (line.product.name if line.product_id else ""),
            "quantity": line.quantity,
            "unit": line.unit,
            "unit_price": line.unit_price,
            "amount": line.line_total,
        }
        for line in quotation.lines.all()
    ]
    return build_priced_document(
        title=f"{t('proforma', lang)} {t('number', lang)} {quotation.reference}",
        party_label=t("billed_to", lang), party=party, info=info, lines=lines,
        total=quotation.total_amount, currency=quotation.currency,
        payment_terms=quotation.payment_terms, notes=quotation.notes, lang=lang,
        banks=quotation.show_bank_accounts, signatures=[],
    )


def render_proforma_pdf(quotation, lang: str = "fr") -> bytes:
    from apps.reports.services.report_pdf import render_report_pdf

    document, rows = build_proforma_document(quotation, lang)
    return render_report_pdf(document, rows, document["lang"])
