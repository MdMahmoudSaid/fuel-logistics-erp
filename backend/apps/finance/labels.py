from apps.finance.models import TreasuryTransaction

# Mirrors ControlledDebtPaymentService._expense_group_label's debt-type
# vocabulary (docs/tresororie_edit.md "Nouveau paiement contrôlé") - the
# journal must describe a paid expense the same way the payment modal's
# "Type de dette" field does, not by its raw Expense.Category value.
_EXPENSE_COUNTERPARTY_BY_CATEGORY = {
    "customs": "Douane",
    "import_intention": "Transit",
    "road": "Frontiere",
    "loading": "Chargement",
}


def _account_name(txn) -> str | None:
    account = txn.bank_account or txn.cash_account
    return account.name if account is not None else None


def _source_counterparty(txn) -> str | None:
    """"Source ou bénéficiaire" for a non-transfer movement, resolved from
    the debt/payment it was posted for (docs/edit.md UI pass 2026-08-26,
    Journal de trésorerie) - e.g. "Fournisseur - Ahmed", "Douane"."""
    source = txn.source_object
    if source is None:
        return None
    model_name = txn.source_content_type.model
    if model_name == "supplierpayment":
        return f"Fournisseur - {source.supplier.name}"
    if model_name == "transportpayment":
        return f"Transporteur - {source.transporter.name}"
    if model_name == "customerpayment":
        return f"Client - {source.customer.name}"
    if model_name == "shareholderwithdrawal":
        return f"Retrait associe - {source.shareholder.name}"
    if model_name == "shareholdercontribution":
        return f"Apport associe - {source.shareholder.name}"
    if model_name == "shareholderloanrepayment":
        return f"Remboursement avance - {source.loan.borrower.name}"
    if model_name == "manualprofit":
        # The reason typed when the profit was added (shown as the reference).
        prefix = "Annulation benefice - " if txn.type == TreasuryTransaction.Type.MONEY_OUT else ""
        return f"{prefix}{source.note}"
    if model_name == "expense":
        return _EXPENSE_COUNTERPARTY_BY_CATEGORY.get(source.category, source.get_category_display())
    return None


def _transfer_counterparty(txn) -> str | None:
    """"Transfert Banque BOA -> Caisse Recette" for an internal transfer.

    TreasuryService.record_transfer() writes exactly two rows sharing
    amount/date/reference, opposite MONEY_IN/MONEY_OUT, both
    is_transfer=True - that's the only link between them, so matching on
    those four fields is how the pair (and therefore the direction) is
    reconstructed for display. Best effort: if two transfers collide on
    all four fields the wrong sibling could be picked, but that only ever
    affects this cosmetic label, never a balance.
    """
    opposite = (
        TreasuryTransaction.Type.MONEY_IN
        if txn.type == TreasuryTransaction.Type.MONEY_OUT
        else TreasuryTransaction.Type.MONEY_OUT
    )
    sibling = (
        TreasuryTransaction.objects.filter(
            is_transfer=True,
            amount=txn.amount,
            date=txn.date,
            reference=txn.reference,
            type=opposite,
        )
        .exclude(pk=txn.pk)
        .first()
    )
    if sibling is None:
        return None
    out_txn, in_txn = (
        (txn, sibling) if txn.type == TreasuryTransaction.Type.MONEY_OUT else (sibling, txn)
    )
    out_name, in_name = _account_name(out_txn), _account_name(in_txn)
    if not out_name or not in_name:
        return None
    return f"Transfert {out_name} -> {in_name}"


def describe_treasury_transaction(txn) -> dict:
    counterparty = _transfer_counterparty(txn) if txn.is_transfer else _source_counterparty(txn)
    return {"counterparty": counterparty}
