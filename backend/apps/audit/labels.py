from django.apps import apps as django_apps

# Stable machine key per audited model, translated client-side (see
# frontend auditLog.modules.* locale keys) - mirrors how `action` is
# already resolved through `auditLog.actions.${action}` rather than
# shipping a French string from the backend.
MODULE_KEYS = {
    "finance.treasurytransaction": "treasury",
    "finance.customerpayment": "customer_payment",
    "finance.supplierpayment": "supplier_payment",
    "finance.transportdeduction": "transport_deduction",
    "finance.expense": "expense",
    "finance.shareholderwithdrawal": "shareholder_withdrawal",
    "purchasing.supplierorder": "supplier_order",
    "trips.deliverycontrol": "delivery_control",
    "sales.sale": "sale",
    "sales.invoice": "invoice",
}


def _snapshot(log) -> dict:
    return log.new_value or log.previous_value or {}


def _lookup_name(app_label: str, model_name: str, pk) -> str | None:
    """Best-effort current display name for a FK id captured in a
    snapshot. The row may since have been deleted (or renamed) - the
    audit trail must never break or lie because of that, so any failure
    just means "no label", not an error."""
    if pk is None:
        return None
    try:
        model = django_apps.get_model(app_label, model_name)
        return str(model.objects.get(pk=pk))
    except Exception:
        return None


def _account_label(snapshot: dict) -> str | None:
    return _lookup_name(
        "finance", "BankAccount", snapshot.get("bank_account_id")
    ) or _lookup_name("finance", "CashAccount", snapshot.get("cash_account_id"))


def describe(log) -> dict:
    """Human-readable summary of an audit log entry for the frontend:
    which module it belongs to, a readable reference/party for the
    object touched, the linked bank/cash account, and the money amount
    involved (see docs/edit.md UI pass 2026-08-26, Journal d'audit).

    Reads only already-captured snapshot fields plus best-effort related
    lookups - never re-derives business figures, so it can't disagree
    with the actual financial record.
    """
    content_type_label = f"{log.content_type.app_label}.{log.content_type.model}"
    snapshot = _snapshot(log)
    module_key = MODULE_KEYS.get(content_type_label, content_type_label)

    reference: str | None = None
    related_party: str | None = None
    account_label: str | None = None
    amount = snapshot.get("amount") or snapshot.get("total_amount")

    if content_type_label == "sales.invoice":
        reference = snapshot.get("invoice_number")
    elif content_type_label == "purchasing.supplierorder":
        reference = snapshot.get("reference")
        related_party = _lookup_name("suppliers", "Supplier", snapshot.get("supplier_id"))
    elif content_type_label == "finance.supplierpayment":
        related_party = _lookup_name("suppliers", "Supplier", snapshot.get("supplier_id"))
        reference = snapshot.get("reference")
        account_label = _account_label(snapshot)
    elif content_type_label == "finance.customerpayment":
        related_party = _lookup_name("customers", "Customer", snapshot.get("customer_id"))
        reference = snapshot.get("reference")
        account_label = _account_label(snapshot)
    elif content_type_label == "finance.transportdeduction":
        related_party = _lookup_name("transport", "Transporter", snapshot.get("transporter_id"))
        reference = _lookup_name("trips", "Trip", snapshot.get("trip_id"))
    elif content_type_label == "finance.shareholderwithdrawal":
        related_party = _lookup_name("finance", "Shareholder", snapshot.get("shareholder_id"))
        account_label = _account_label(snapshot)
    elif content_type_label == "finance.treasurytransaction":
        reference = snapshot.get("reference")
        account_label = _account_label(snapshot)
    elif content_type_label == "sales.sale":
        related_party = _lookup_name("customers", "Customer", snapshot.get("customer_id"))
        reference = _lookup_name("trips", "Trip", snapshot.get("trip_id"))
    elif content_type_label == "trips.deliverycontrol":
        reference = _lookup_name("trips", "Trip", snapshot.get("trip_id"))
    elif content_type_label == "finance.expense":
        reference = snapshot.get("category")

    return {
        "module_key": module_key,
        "reference": reference,
        "related_party": related_party,
        "account_label": account_label,
        "amount": str(amount) if amount is not None else None,
    }
