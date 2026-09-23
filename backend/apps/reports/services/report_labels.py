# Translated labels for the report document (docs/superpowers/specs/2026-09-23-
# rapports-document-comptable-design.md, D2: the backend is the single source
# of report labels; the Vue sheet and the PDF both render what the document
# builder returns). Every entry is a (fr, en, ar) tuple, flattened into
# LABELS[lang][key] at the bottom of the module.
#
# Key families: title.<slug>, field.<name> (optionally field.<slug>.<name> to
# override for one report), summary.<key>, entity.<kind>, ui.<key>,
# enum.<namespace>.<VALUE>. Enum values reuse the frontend locale wording
# (statementType, purchaseOrderStatus, ...); CONTRIBUTION and the fuel-stock
# components are not in the frontend files and are defined here.

TITLES = {
    "customer-statement": ("Relevé client", "Customer statement", "كشف حساب العميل"),
    "supplier-statement": ("Relevé fournisseur", "Supplier statement", "كشف حساب المورد"),
    "transporter-statement": ("Relevé transporteur", "Transporter statement", "كشف حساب الناقل"),
    "truck-history": ("Historique camion", "Truck history", "سجل الشاحنة"),
    "trip-report": ("Rapport des trajets", "Trip report", "تقرير الرحلات"),
    "purchase-report": ("Rapport des achats", "Purchase report", "تقرير المشتريات"),
    "sales-report": ("Rapport des ventes", "Sales report", "تقرير المبيعات"),
    "expense-report": ("Rapport des dépenses", "Expense report", "تقرير المصروفات"),
    "customer-outstanding": ("Impayés clients", "Customer outstanding", "مستحقات العملاء"),
    "supplier-outstanding": ("Impayés fournisseurs", "Supplier outstanding", "مستحقات الموردين"),
    "transporter-outstanding": ("Impayés transporteurs", "Transporter outstanding", "مستحقات الناقلين"),
    "fuel-stock": ("Stock carburant", "Fuel stock", "مخزون الوقود"),
    "loss-report": ("Rapport des écarts", "Loss report", "تقرير الفروقات"),
    "margin-report": ("Rapport de marge", "Margin report", "تقرير الهامش"),
    "bank-statement": ("Relevé bancaire", "Bank statement", "كشف الحساب البنكي"),
    "cash-statement": ("Relevé de caisse", "Cash statement", "كشف حساب الصندوق"),
    "shareholder-statement": ("Relevé actionnaire", "Shareholder statement", "كشف حساب المساهم"),
}

FIELDS = {
    "date": ("Date", "Date", "التاريخ"),
    "type": ("Type", "Type", "النوع"),
    "reference": ("Référence", "Reference", "المرجع"),
    "debit": ("Débit", "Debit", "مدين"),
    "credit": ("Crédit", "Credit", "دائن"),
    "balance": ("Solde", "Balance", "الرصيد"),
    "amount": ("Montant", "Amount", "المبلغ"),
    "trip_reference": ("Trajet", "Trip", "الرحلة"),
    "base_amount": ("Montant brut", "Gross amount", "المبلغ الإجمالي"),
    "deduction_amount": ("Retenue", "Deduction", "الخصم"),
    "advance_applied": ("Avance déduite", "Advance deducted", "السلفة المخصومة"),
    "net_amount": ("Montant net", "Net amount", "المبلغ الصافي"),
    "loading_date": ("Date de chargement", "Loading date", "تاريخ التحميل"),
    "status": ("Statut", "Status", "الحالة"),
    "quantity_loaded": ("Qté chargée", "Loaded qty", "الكمية المحمّلة"),
    "client": ("Client", "Client", "العميل"),
    "current_margin": ("Marge", "Margin", "الهامش"),
    "truck": ("Camion", "Truck", "الشاحنة"),
    "transporter": ("Transporteur", "Transporter", "الناقل"),
    "supplier": ("Fournisseur", "Supplier", "المورد"),
    "product": ("Produit", "Product", "المنتج"),
    "purchase_date": ("Date", "Date", "التاريخ"),
    "quantity_litres": ("Qté (L)", "Qty (L)", "الكمية (لتر)"),
    "unit_price": ("Prix unitaire", "Unit price", "سعر الوحدة"),
    "total_amount": ("Total", "Total", "الإجمالي"),
    "customer": ("Client", "Customer", "العميل"),
    "delivered_quantity": ("Qté livrée", "Delivered qty", "الكمية المسلّمة"),
    "unit_selling_price": ("Prix de vente", "Selling price", "سعر البيع"),
    "subtotal": ("Sous-total", "Subtotal", "المجموع الفرعي"),
    "category": ("Catégorie", "Category", "الفئة"),
    "calculation_method": ("Méthode de calcul", "Calculation method", "طريقة الحساب"),
    "outstanding": ("Montant restant", "Amount outstanding", "المبلغ المتبقي"),
    "component": ("Composant", "Component", "المكوّن"),
    "quantity": ("Quantité", "Quantity", "الكمية"),
    "control_date": ("Date de contrôle", "Control date", "تاريخ المراقبة"),
    "loaded_quantity": ("Qté chargée", "Loaded qty", "الكمية المحمّلة"),
    "received_quantity": ("Qté reçue", "Received qty", "الكمية المستلمة"),
    "loss_quantity": ("Perte", "Loss", "الفاقد"),
    "tolerance_quantity": ("Tolérance", "Tolerance", "المسموح به"),
    "chargeable_loss_quantity": ("Perte facturable", "Chargeable loss", "الفاقد القابل للفوترة"),
    "verified_at": ("Vérifié le", "Verified on", "تاريخ التحقق"),
    "notes": ("Notes", "Notes", "ملاحظات"),
    "quantity_invoiced": ("Qté facturée", "Invoiced qty", "الكمية المفوترة"),
    "transporter_loss_quantity": ("Perte transporteur (qté)", "Transporter loss (qty)", "فاقد الناقل (كمية)"),
    "company_absorbed_loss_quantity": ("Perte société (qté)", "Company loss (qty)", "فاقد الشركة (كمية)"),
    "supplier_unit_price": ("Prix fournisseur", "Supplier price", "سعر المورد"),
    "transport_cost": ("Transport", "Transport", "النقل"),
    "customs_cost": ("Douane", "Customs", "الجمارك"),
    "transit_cost": ("Transit", "Transit", "العبور"),
    "road_transit_cost": ("Transit routier", "Road transit", "العبور البري"),
    "border_cost": ("Frontière", "Border", "الحدود"),
    "loading_cost": ("Chargement", "Loading", "التحميل"),
    "additional_costs": ("Frais additionnels", "Additional costs", "تكاليف إضافية"),
    "real_total_cost": ("Coût réel total", "Total real cost", "التكلفة الفعلية الإجمالية"),
    "transporter_loss_indemnity": ("Indemnité transporteur", "Transporter indemnity", "تعويض الناقل"),
    "company_absorbed_loss_amount": ("Perte absorbée", "Absorbed loss", "الفاقد المتحمَّل"),
    "unit_cost": ("Coût unitaire", "Unit cost", "تكلفة الوحدة"),
    "unit_profit": ("Profit unitaire", "Unit profit", "ربح الوحدة"),
    # Per-report overrides (field.<slug>.<name>)
    "margin-report.quantity": ("Qté", "Qty", "الكمية"),
}

TABLE_TITLES = {
    "margin-report.1": ("Quantités et prix", "Quantities and prices", "الكميات والأسعار"),
    "margin-report.2": ("Coûts", "Costs", "التكاليف"),
    "margin-report.3": ("Pertes et marge", "Losses and margin", "الفاقد والهامش"),
}

SUMMARY = {
    "opening_balance": ("Solde antérieur", "Opening balance", "الرصيد السابق"),
    "total_debit": ("Total débit", "Total debit", "إجمالي المدين"),
    "total_credit": ("Total crédit", "Total credit", "إجمالي الدائن"),
    "net_movement": ("Mouvement net de la période", "Net movement for the period", "صافي حركة الفترة"),
    "closing_balance": ("Solde final", "Closing balance", "الرصيد النهائي"),
    "total_in": ("Total entrées", "Total in", "إجمالي الوارد"),
    "total_out": ("Total sorties", "Total out", "إجمالي الصادر"),
    "internal_transfers": ("Virements internes (net)", "Internal transfers (net)", "التحويلات الداخلية (صافي)"),
    "reconciliation_gap": ("Écart de rapprochement", "Reconciliation gap", "فرق المطابقة"),
    "total_base_amount": ("Total montant brut", "Total gross amount", "إجمالي المبلغ الإجمالي"),
    "total_deduction": ("Total retenues", "Total deductions", "إجمالي الخصومات"),
    "total_advance": ("Total avances déduites", "Total advances deducted", "إجمالي السلف المخصومة"),
    "total_net": ("Total montant net", "Total net amount", "إجمالي المبلغ الصافي"),
    "trips_count": ("Nombre de trajets", "Number of trips", "عدد الرحلات"),
    "total_quantity": ("Quantité totale", "Total quantity", "إجمالي الكمية"),
    "margin_total": ("Marge totale", "Total margin", "إجمالي الهامش"),
    "orders_count": ("Nombre de commandes", "Number of orders", "عدد الطلبات"),
    "total_amount": ("Montant total", "Total amount", "المبلغ الإجمالي"),
    "total_delivered": ("Quantité livrée totale", "Total delivered quantity", "إجمالي الكمية المسلّمة"),
    "total_subtotal": ("Total des ventes", "Total sales", "إجمالي المبيعات"),
    "expenses_count": ("Nombre de dépenses", "Number of expenses", "عدد المصروفات"),
    "total_outstanding": ("Total restant dû", "Total outstanding", "إجمالي المتبقي"),
    "customers_count": ("Nombre de clients", "Number of customers", "عدد العملاء"),
    "suppliers_count": ("Nombre de fournisseurs", "Number of suppliers", "عدد الموردين"),
    "transporters_count": ("Nombre de transporteurs", "Number of transporters", "عدد الناقلين"),
    "supplier_reliquat": ("Reliquat fournisseurs", "Supplier balances", "أرصدة الموردين"),
    "loaded_unsold": ("Chargé non vendu", "Loaded, unsold", "محمّل غير مباع"),
    "total_stock": ("Stock théorique total", "Total theoretical stock", "إجمالي المخزون النظري"),
    "total_loaded": ("Quantité chargée totale", "Total loaded quantity", "إجمالي الكمية المحمّلة"),
    "total_received": ("Quantité reçue totale", "Total received quantity", "إجمالي الكمية المستلمة"),
    "total_loss": ("Perte totale", "Total loss", "إجمالي الفاقد"),
    "total_chargeable": ("Perte facturable totale", "Total chargeable loss", "إجمالي الفاقد القابل للفوترة"),
    "total_quantity_loaded": ("Quantité chargée totale", "Total loaded quantity", "إجمالي الكمية المحمّلة"),
    "total_invoiced": ("Quantité facturée totale", "Total invoiced quantity", "إجمالي الكمية المفوترة"),
    "total_real_cost": ("Coût réel total", "Total real cost", "التكلفة الفعلية الإجمالية"),
    "cancelled_excluded": ("Annulés exclus", "Cancelled excluded", "الملغاة المستبعدة"),
}

ENTITY = {
    "customer": ("Client", "Customer", "العميل"),
    "supplier": ("Fournisseur", "Supplier", "المورد"),
    "transporter": ("Transporteur", "Transporter", "الناقل"),
    "truck": ("Camion", "Truck", "الشاحنة"),
    "bank_account": ("Compte bancaire", "Bank account", "الحساب البنكي"),
    "cash_account": ("Caisse", "Cash account", "الصندوق"),
    "shareholder": ("Associé", "Shareholder", "المساهم"),
}

UI = {
    "empty_text": (
        "Aucune donnée pour la période sélectionnée.",
        "No data for the selected period.",
        "لا توجد بيانات للفترة المحددة.",
    ),
    "generated_on": ("Généré le", "Generated on", "تاريخ الإنشاء"),
    "period": ("Période", "Period", "الفترة"),
    "currency": ("Devise", "Currency", "العملة"),
    "period_range": ("Du {from} au {to}", "From {from} to {to}", "من {from} إلى {to}"),
    "period_from": ("À partir du {from}", "From {from}", "ابتداءً من {from}"),
    "period_to": ("Jusqu'au {to}", "Until {to}", "حتى {to}"),
    "period_open": ("Toutes périodes", "All periods", "كل الفترات"),
    "period_as_of": ("Situation au {date}", "As of {date}", "الوضع بتاريخ {date}"),
    "page": ("Page {n} / {total}", "Page {n} / {total}", "صفحة {n} / {total}"),
}

ENUMS = {
    "statementType": {
        "INVOICE": ("Facture", "Invoice", "فاتورة"),
        "PURCHASE": ("Achat", "Purchase", "شراء"),
        "PAYMENT": ("Paiement", "Payment", "دفعة"),
        "PROFIT_SHARE": ("Bénéfice attribué", "Profit share", "حصة أرباح"),
        "WITHDRAWAL": ("Retrait", "Withdrawal", "سحب"),
        "LOAN_GIVEN": ("Avance donnée", "Loan given", "سلفة ممنوحة"),
        "LOAN_RECEIVED": ("Avance reçue", "Loan received", "سلفة مستلمة"),
        "CONTRIBUTION": ("Apport en capital", "Capital contribution", "مساهمة في رأس المال"),
    },
    "transactionType": {
        "MONEY_IN": ("Entrée", "In", "وارد"),
        "MONEY_OUT": ("Sortie", "Out", "صادر"),
        "TRANSFER": ("Transfert", "Transfer", "تحويل"),
    },
    "purchaseOrderStatus": {
        "DRAFT": ("Brouillon", "Draft", "مسودة"),
        "CONFIRMED": ("Confirmée", "Confirmed", "مؤكد"),
        "CANCELLED": ("Annulée", "Cancelled", "ملغى"),
    },
    "expenseStatus": {
        "UNPAID": ("Non payé", "Unpaid", "غير مدفوع"),
        "PARTIALLY_PAID": ("Partiellement payé", "Partially paid", "مدفوع جزئيًا"),
        "PAID": ("Payé", "Paid", "مدفوع"),
        "CANCELLED": ("Annulé", "Cancelled", "ملغى"),
    },
    "expenseCategory": {
        "customs": ("Douane", "Customs", "الجمارك"),
        "import_intention": ("Intention d'importation", "Import intention", "نية الاستيراد"),
        "transit": ("Transit", "Transit", "العبور"),
        "road_transit": ("Transit routière", "Road transit", "العبور البري"),
        "transport": ("Transport", "Transport", "النقل"),
        "loading": ("Chargement", "Loading", "التحميل"),
        "unloading": ("Déchargement", "Unloading", "التفريغ"),
        "road": ("Frontière", "Border", "الحدود"),
        "administration": ("Administration", "Administration", "الإدارة"),
        "rent": ("Loyer", "Rent", "الإيجار"),
        "salary": ("Salaire", "Salary", "الراتب"),
        "repairs": ("Réparations", "Repairs", "الإصلاحات"),
        "bank_charges": ("Frais bancaires", "Bank charges", "الرسوم البنكية"),
        "other": ("Autre", "Other", "آخر"),
    },
    "expenseCalcMethod": {
        "FIXED": ("Fixe", "Fixed", "ثابت"),
        "PER_LITRE": ("Par litre", "Per litre", "لكل لتر"),
        "PERCENTAGE": ("Pourcentage", "Percentage", "نسبة مئوية"),
        "PER_ORDER": ("Par commande", "Per order", "لكل طلب"),
        "PER_TRUCK": ("Par camion", "Per truck", "لكل شاحنة"),
        "MANUAL": ("Manuel", "Manual", "يدوي"),
    },
    "tripStatus": {
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
    },
    "fuelComponent": {
        "SUPPLIER_RELIQUAT": ("Reliquat fournisseur", "Supplier balance", "رصيد المورد"),
        "LOADED_UNSOLD": ("Chargé non vendu", "Loaded, unsold", "محمّل غير مباع"),
        "TOTAL": ("Stock théorique total", "Total theoretical stock", "إجمالي المخزون النظري"),
    },
}


def _flatten() -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {"fr": {}, "en": {}, "ar": {}}
    families = {
        "title": TITLES,
        "field": FIELDS,
        "table": TABLE_TITLES,
        "summary": SUMMARY,
        "entity": ENTITY,
        "ui": UI,
    }
    for prefix, table in families.items():
        for key, values in table.items():
            for index, lang in enumerate(("fr", "en", "ar")):
                labels[lang][f"{prefix}.{key}"] = values[index]
    for namespace, entries in ENUMS.items():
        for value, translations in entries.items():
            for index, lang in enumerate(("fr", "en", "ar")):
                labels[lang][f"enum.{namespace}.{value}"] = translations[index]
    return labels


LABELS = _flatten()
ENUM_NAMESPACES = tuple(ENUMS)
