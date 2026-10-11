# PDFs of the commercial documents (spec 2026-10-11 documents-commerciaux
# §4-§6): delivery note (after the client's Sahel Commerce note N°004),
# loading sheet (after the "liste des camions" of 29/06) and purchase order
# (a priced document, like the proforma). All rendered by the shared
# report_pdf engine.

from decimal import Decimal

from apps.reports.services.proforma_pdf import (
    LANGS,
    base_document,
    build_priced_document,
    column,
    fmt_date,
)
from apps.reports.services.proforma_pdf import t as priced_t

TEXT = {
    "delivery_title": ("Bon de livraison", "Delivery note", "إذن تسليم"),
    "loading_title": ("Liste des camions au compte de {name}", "Trucks loaded on behalf of {name}",
                      "قائمة الشاحنات لحساب {name}"),
    "number": ("N°", "No.", "رقم"),
    "place_date": ("Lieu et date", "Place and date", "المكان والتاريخ"),
    "customer": ("Client", "Customer", "العميل"),
    "delivery_address": ("Adresse de livraison", "Delivery address", "عنوان التسليم"),
    "date": ("Date", "Date", "التاريخ"),
    "supplier": ("Fournisseur / dépôt", "Supplier / depot", "المورد / المستودع"),
    "reference": ("Référence", "Reference", "المرجع"),
    "product": ("Produit", "Product", "المنتج"),
    "route": ("Axe", "Route", "المحور"),
    "row": ("N°", "No.", "رقم"),
    "designation": ("Désignation", "Description", "البيان"),
    "quantity": ("Quantité", "Quantity", "الكمية"),
    "tanker": ("Citerne", "Tanker", "الصهريج"),
    "tractor": ("Tracteur", "Tractor", "الجرار"),
    "missing": ("Manquant", "Shortage", "النقص"),
    "observation": ("Observation", "Remark", "ملاحظة"),
    "capacity": ("Capacité (L)", "Capacity (L)", "السعة (لتر)"),
    "be": ("N° BE", "Loading order no.", "رقم أمر التعبئة"),
    "lines": ("Détail", "Details", "التفاصيل"),
    "total_qty": ("Quantité totale", "Total quantity", "الكمية الإجمالية"),
    "trucks": ("Nombre de camions", "Number of trucks", "عدد الشاحنات"),
    "total_litres": ("Total (L)", "Total (L)", "المجموع (لتر)"),
    "receiver": ("Le réceptionnaire", "The receiver", "المستلم"),
    "supplier_sig": ("Le fournisseur", "The supplier", "المورد"),
    "notes": ("Observations", "Remarks", "ملاحظات"),
}


def _t(key: str, lang: str) -> str:
    return TEXT[key][LANGS.index(lang)]


def _lang(lang: str) -> str:
    return lang if lang in LANGS else "fr"


def _notes_block(notes: str, lang: str) -> list:
    return [{"title": _t("notes", lang), "text": notes}] if notes else []


def build_delivery_note_document(note, lang: str = "fr") -> tuple[dict, list[dict]]:
    lang = _lang(lang)
    place_date = ", ".join(x for x in [note.place, fmt_date(note.date)] if x)
    info = [
        {"label": _t("place_date", lang), "value": place_date},
        {"label": _t("customer", lang), "value": note.customer.name},
        {"label": _t("delivery_address", lang), "value": note.delivery_address or note.customer.address},
    ]
    columns = [
        column("number", _t("row", lang), "text"),
        column("designation", _t("designation", lang), "text"),
        column("quantity", _t("quantity", lang), "quantity", "end"),
        column("tanker", _t("tanker", lang), "text"),
        column("tractor", _t("tractor", lang), "text"),
        column("missing", _t("missing", lang), "quantity", "end"),
        column("observation", _t("observation", lang), "text"),
    ]
    lines = list(note.lines.all())
    rows = [
        {"number": index, "designation": line.designation, "quantity": line.quantity, "tanker": line.tanker,
         "tractor": line.tractor, "missing": line.missing, "observation": line.observation}
        for index, line in enumerate(lines, start=1)
    ]
    total = sum((line.quantity for line in lines), Decimal("0.00"))
    document = base_document(
        title=f"{_t('delivery_title', lang)} {_t('number', lang)} {note.reference}",
        lang=lang, info=info, tables=[{"title": _t("lines", lang), "columns": columns}],
        summary=[{"label": _t("total_qty", lang), "value": total, "kind": "quantity", "emphasis": True}],
        blocks=_notes_block(note.notes, lang), signatures=[_t("receiver", lang), _t("supplier_sig", lang)],
    )
    return document, rows


def build_loading_sheet_document(sheet, lang: str = "fr") -> tuple[dict, list[dict]]:
    from apps.core.models import CompanyProfile

    lang = _lang(lang)
    on_behalf_of = sheet.on_behalf_of or CompanyProfile.load().pdf_company()["name"]
    info = [
        {"label": _t("date", lang), "value": fmt_date(sheet.date)},
        {"label": _t("supplier", lang), "value": sheet.supplier_display_name},
        {"label": _t("reference", lang), "value": sheet.source_reference},
        {"label": _t("product", lang), "value": sheet.product_name},
        {"label": _t("route", lang), "value": sheet.route},
    ]
    columns = [
        column("number", _t("row", lang), "text"),
        column("tractor", _t("tractor", lang), "text"),
        column("tanker", _t("tanker", lang), "text"),
        column("capacity", _t("capacity", lang), "quantity", "end"),
        column("product", _t("product", lang), "text"),
        column("be", _t("be", lang), "text"),
        column("route", _t("route", lang), "text"),
    ]
    lines = list(sheet.lines.all())
    rows = [
        {"number": index, "tractor": line.tractor, "tanker": line.tanker, "capacity": line.capacity_litres,
         "product": line.product_name or sheet.product_name, "be": line.be_number,
         "route": line.route or sheet.route}
        for index, line in enumerate(lines, start=1)
    ]
    total = sum((line.capacity_litres for line in lines), Decimal("0.00"))
    document = base_document(
        title=_t("loading_title", lang).format(name=on_behalf_of) + f" · {sheet.reference}",
        lang=lang, info=info, tables=[{"title": _t("lines", lang), "columns": columns}],
        summary=[
            {"label": _t("trucks", lang), "value": len(lines), "kind": "text", "emphasis": False},
            {"label": _t("total_litres", lang), "value": total, "kind": "quantity", "emphasis": True},
        ],
        blocks=_notes_block(sheet.notes, lang), signatures=[], orientation="landscape",
    )
    return document, rows


def build_purchase_order_document(order, lang: str = "fr") -> tuple[dict, list[dict]]:
    lang = _lang(lang)
    supplier = order.supplier
    info = [
        {"label": priced_t("date", lang), "value": fmt_date(order.date)},
        {"label": priced_t("delivery_date", lang), "value": fmt_date(order.delivery_date)},
        {"label": priced_t("delivery_place", lang), "value": order.delivery_place},
        {"label": priced_t("currency", lang), "value": order.currency},
    ]
    lines = [
        {"designation": line.description or (line.product.name if line.product_id else ""),
         "quantity": line.quantity, "unit": line.unit, "unit_price": line.unit_price, "amount": line.line_total}
        for line in order.lines.all()
    ]
    return build_priced_document(
        title=f"{priced_t('order', lang)} {priced_t('number', lang)} {order.reference}",
        party_label=priced_t("supplier", lang),
        party={"name": supplier.name, "address": getattr(supplier, "address", ""),
               "phone": getattr(supplier, "phone", "")},
        info=info, lines=lines, total=order.total_amount, currency=order.currency,
        payment_terms=order.payment_terms, notes=order.notes, lang=lang, banks=False,
        signatures=[priced_t("for_company", lang)],
    )


def _render(builder):
    def render(document_model, lang: str = "fr") -> bytes:
        from apps.reports.services.report_pdf import render_report_pdf

        document, rows = builder(document_model, lang)
        return render_report_pdf(document, rows, document["lang"])

    return render


render_delivery_note_pdf = _render(build_delivery_note_document)
render_loading_sheet_pdf = _render(build_loading_sheet_document)
render_purchase_order_pdf = _render(build_purchase_order_document)
