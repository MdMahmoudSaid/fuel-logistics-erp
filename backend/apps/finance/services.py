# Financial domain services (docs/PHASE_5_PLAN.md Etape 6;
# ERP_Implementation_Experience_Guide.md Section 8.4/8.9/8.10/1.6/1.7).
#
# Payment and payment allocation are separate concerns (guide Section 8.1):
# CustomerPayment/SupplierPayment never carry an invoice FK themselves, so
# every "how much is still owed" question is answered by summing allocation
# rows here - once, so no two API paths can compute a different outstanding
# balance for the same invoice/customer (guide Section 8.4).

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    PaymentAllocation,
    Shareholder,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    SupplierPayment,
    TreasuryTransaction,
)
from apps.sales.models import Invoice

ZERO = Decimal("0.00")


class PaymentAllocationError(ValueError):
    """Raised when an allocation would overdraw its payment or overpay its
    invoice."""


class PaymentAllocationService:
    """Owns CustomerPayment -> Invoice imputation (guide Section 8.3/8.4)."""

    @staticmethod
    def get_invoice_outstanding(invoice: Invoice) -> Decimal:
        allocated = invoice.allocations.aggregate(total=Sum("amount"))["total"] or ZERO
        return invoice.total_amount - allocated

    @staticmethod
    def get_customer_outstanding(customer) -> Decimal:
        """Total invoiced (non-cancelled) minus total received, regardless
        of per-invoice allocation state - money the company has already
        collected always reduces what the customer still owes, even while
        it sits as unallocated credit (guide Section 8.3)."""
        total_invoiced = (
            Invoice.objects.filter(sale__customer=customer)
            .exclude(status=Invoice.Status.CANCELLED)
            .aggregate(total=Sum("total_amount"))["total"]
            or ZERO
        )
        total_received = (
            customer.payments.aggregate(total=Sum("amount"))["total"] or ZERO
        )
        return total_invoiced - total_received

    @staticmethod
    @transaction.atomic
    def allocate_payment(payment_id, invoice_allocations: list[dict]) -> list[PaymentAllocation]:
        """Create one PaymentAllocation per item in `invoice_allocations`
        (each `{"invoice_id": int | None, "amount": Decimal}`, None meaning
        unallocated credit), under a row lock on the payment so concurrent
        allocation calls can't jointly overdraw it (docs/PHASE_5_PLAN.md
        Etape 6: "sous verrou select_for_update sur CustomerPayment").
        """
        payment = CustomerPayment.objects.select_for_update().get(pk=payment_id)

        requested_total = sum(
            (Decimal(str(item["amount"])) for item in invoice_allocations), ZERO
        )
        already_allocated = (
            payment.allocations.aggregate(total=Sum("amount"))["total"] or ZERO
        )
        if already_allocated + requested_total > payment.amount:
            raise PaymentAllocationError(
                f"Allocation totale ({already_allocated + requested_total}) "
                f"depasse le montant du paiement ({payment.amount})."
            )

        created = []
        for item in invoice_allocations:
            amount = Decimal(str(item["amount"]))
            invoice_id = item.get("invoice_id") or item.get("invoice")
            invoice = None
            if invoice_id:
                invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
                outstanding = PaymentAllocationService.get_invoice_outstanding(invoice)
                if amount > outstanding:
                    raise PaymentAllocationError(
                        f"Le montant alloue ({amount}) depasse l'encours de la "
                        f"facture {invoice.invoice_number} ({outstanding})."
                    )

            allocation = PaymentAllocation.objects.create(
                payment=payment, invoice=invoice, amount=amount
            )
            created.append(allocation)

            if invoice is not None:
                PaymentAllocationService._sync_invoice_status(invoice)

        return created

    @staticmethod
    def _sync_invoice_status(invoice: Invoice) -> None:
        """Move VALIDATED -> PARTIALLY_PAID -> PAID as allocations land.
        Never touches DRAFT/CANCELLED invoices - those aren't payable yet
        or shouldn't have been paid at all."""
        if invoice.status not in (
            Invoice.Status.VALIDATED,
            Invoice.Status.PARTIALLY_PAID,
            Invoice.Status.PAID,
        ):
            return

        outstanding = PaymentAllocationService.get_invoice_outstanding(invoice)
        if outstanding <= ZERO:
            target = Invoice.Status.PAID
        elif outstanding < invoice.total_amount:
            target = Invoice.Status.PARTIALLY_PAID
        else:
            target = invoice.status

        if target != invoice.status:
            invoice.status = target
            invoice.save(update_fields=["status", "updated_at"])


class IndirectSettlementService:
    """Records a customer-paid-operational-expense event without ever
    touching treasury (docs/PHASE_5_PLAN.md Etape 6; guide Section 1.6/8.9:
    "do NOT create TreasuryTransaction" - the money never transited through
    a company bank/cash account)."""

    @staticmethod
    @transaction.atomic
    def record_indirect_payment(customer_id, expense_data: dict, actor, invoice_id=None):
        from apps.customers.models import Customer

        customer = Customer.objects.select_for_update().get(pk=customer_id)

        if invoice_id is not None:
            invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
            if invoice.sale.customer_id != customer.id:
                raise ValueError(
                    f"La facture {invoice.invoice_number} n'appartient pas a ce client."
                )
        else:
            invoice = None

        expense = Expense.objects.create(
            category=expense_data["category"],
            amount=expense_data["amount"],
            calculation_method=expense_data.get(
                "calculation_method", Expense.CalculationMethod.MANUAL
            ),
            date=expense_data["date"],
            status=Expense.Status.PAID,
            paid_by_customer_directly=True,
            notes=expense_data.get("notes", ""),
        )

        payment = CustomerPayment.objects.create(
            customer=customer,
            amount=expense.amount,
            payment_date=expense.date,
            method=CustomerPayment.Method.OTHER,
            bank_account=None,
            cash_account=None,
            reference=expense_data.get("reference", ""),
            is_indirect=True,
            destination=CustomerPayment.Destination.INDIRECT,
            recorded_by=actor,
        )

        allocation = PaymentAllocation.objects.create(
            payment=payment, invoice=invoice, amount=expense.amount
        )
        if invoice is not None:
            PaymentAllocationService._sync_invoice_status(invoice)

        return expense, payment, allocation


class FinancePostingService:
    """Posts a direct CustomerPayment to company treasury (Task 4, client
    modifications plan; docs/PHASE_5_PLAN.md conventions Etape 6: separate
    service, @staticmethod, transaction.atomic, select_for_update() on the
    account being credited).

    Indirect payments never reach treasury at all (guide Section 1.6,
    IndirectSettlementService docstring) - this service is the other half
    of that split: the ONLY place that turns a direct CustomerPayment into
    a TreasuryTransaction(MONEY_IN), so every direct payment posts through
    one code path regardless of whether it came from the plain create API
    or some future bulk-import flow.
    """

    # Placeholder cash account for the VERS_MOI destination (money handed
    # personally to someone rather than deposited to a named bank/cash
    # account) - dashboard treasury must still account for it, so it still
    # needs a real CashAccount row to post against (Task 4, client
    # modifications plan).
    VERS_MOI_ACCOUNT_NAME = "Vers moi"

    @staticmethod
    def get_or_create_vers_moi_account() -> CashAccount:
        # CashAccount.name has no unique DB constraint, so get_or_create is
        # the only thing standing between this and duplicate "Vers moi" rows.
        account, _created = CashAccount.objects.get_or_create(
            name=FinancePostingService.VERS_MOI_ACCOUNT_NAME
        )
        return account

    @staticmethod
    @transaction.atomic
    def record_customer_payment_treasury(payment: CustomerPayment) -> TreasuryTransaction | None:
        """Create the one TreasuryTransaction(MONEY_IN) a direct customer
        payment must produce, linked back via source_content_type/
        source_object_id. Returns None (no-op) for an indirect payment or
        for a payment that was already posted - callers don't need to
        check either case themselves.
        """
        if payment.is_indirect:
            return None

        payment_content_type = ContentType.objects.get_for_model(CustomerPayment)
        already_posted = TreasuryTransaction.objects.filter(
            source_content_type=payment_content_type, source_object_id=payment.id
        ).exists()
        if already_posted:
            return None

        if payment.bank_account_id:
            bank_account = BankAccount.objects.select_for_update().get(pk=payment.bank_account_id)
            cash_account = None
        elif payment.cash_account_id:
            bank_account = None
            cash_account = CashAccount.objects.select_for_update().get(pk=payment.cash_account_id)
        else:
            # Neither account set on a non-indirect payment shouldn't happen
            # given CustomerPaymentSerializer.validate(), but there's
            # nothing sane to post here - stay defensive rather than raise.
            return None

        return TreasuryTransaction.objects.create(
            bank_account=bank_account,
            cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_IN,
            amount=payment.amount,
            date=payment.payment_date,
            reference=payment.reference,
            source_content_type=payment_content_type,
            source_object_id=payment.id,
            recorded_by=payment.recorded_by,
        )

    @staticmethod
    @transaction.atomic
    def record_supplier_payment_treasury(payment: SupplierPayment) -> TreasuryTransaction | None:
        """Create the one TreasuryTransaction(MONEY_OUT) every SupplierPayment
        must produce (Task 5, client modifications plan). Unlike
        CustomerPayment there is no indirect case for SupplierPayment, and
        unlike the bank-only restriction on debt repayment (enforced by
        SupplierPaymentSerializer.validate()), an advance (is_advance=True)
        is exempt from that restriction but not from this posting: it is
        still real money leaving the company (ruling 2), so every created
        SupplierPayment - advance or not - posts through this one path.
        Returns None (no-op) for a payment that was already posted -
        callers don't need to check that themselves.
        """
        payment_content_type = ContentType.objects.get_for_model(SupplierPayment)
        already_posted = TreasuryTransaction.objects.filter(
            source_content_type=payment_content_type, source_object_id=payment.id
        ).exists()
        if already_posted:
            return None

        if payment.bank_account_id:
            bank_account = BankAccount.objects.select_for_update().get(pk=payment.bank_account_id)
            cash_account = None
        elif payment.cash_account_id:
            bank_account = None
            cash_account = CashAccount.objects.select_for_update().get(pk=payment.cash_account_id)
        else:
            # Neither account set shouldn't happen given the DB-level
            # finance_supplierpayment_requires_account constraint, but
            # there's nothing sane to post here - stay defensive rather
            # than raise.
            return None

        return TreasuryTransaction.objects.create(
            bank_account=bank_account,
            cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_OUT,
            amount=payment.amount,
            date=payment.payment_date,
            reference=payment.reference,
            source_content_type=payment_content_type,
            source_object_id=payment.id,
            recorded_by=payment.recorded_by,
        )


    @staticmethod
    @transaction.atomic
    def record_shareholder_withdrawal_treasury(
        withdrawal: ShareholderWithdrawal,
    ) -> TreasuryTransaction | None:
        """Create the one TreasuryTransaction(MONEY_OUT) every
        ShareholderWithdrawal must produce (Task 7, client modifications
        plan) - same mechanics as record_supplier_payment_treasury:
        select_for_update on the account actually debited, linked back via
        source_content_type/source_object_id, idempotent against
        already-posted withdrawals.
        """
        withdrawal_content_type = ContentType.objects.get_for_model(ShareholderWithdrawal)
        already_posted = TreasuryTransaction.objects.filter(
            source_content_type=withdrawal_content_type, source_object_id=withdrawal.id
        ).exists()
        if already_posted:
            return None

        if withdrawal.bank_account_id:
            bank_account = BankAccount.objects.select_for_update().get(pk=withdrawal.bank_account_id)
            cash_account = None
        elif withdrawal.cash_account_id:
            bank_account = None
            cash_account = CashAccount.objects.select_for_update().get(pk=withdrawal.cash_account_id)
        else:
            # Neither account set shouldn't happen given the DB-level
            # finance_shareholderwithdrawal_requires_account constraint, but
            # there's nothing sane to post here - stay defensive rather
            # than raise.
            return None

        return TreasuryTransaction.objects.create(
            bank_account=bank_account,
            cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_OUT,
            amount=withdrawal.amount,
            date=withdrawal.date,
            reference="",
            source_content_type=withdrawal_content_type,
            source_object_id=withdrawal.id,
            recorded_by=withdrawal.recorded_by,
        )


class TreasuryTransferError(ValueError):
    """Raised for an invalid internal transfer request (same account on
    both sides, unknown account type, ...)."""


class TreasuryService:
    """Owns treasury movements not tied to a specific payment/expense flow
    (docs/PHASE_5_PLAN.md Etape 6; guide Section 8.10/D)."""

    _ACCOUNT_MODELS = {"bank": BankAccount, "cash": CashAccount}

    @staticmethod
    @transaction.atomic
    def record_transfer(
        source_account_type,
        source_account_id,
        dest_account_type,
        dest_account_id,
        amount,
        date,
        reference,
        user,
    ):
        """Move money between two treasury accounts as exactly two
        TreasuryTransaction rows (type=MONEY_OUT on the source,
        type=MONEY_IN on the destination - so BankAccount/CashAccount.
        current_balance can sum them like any other movement), both
        is_transfer=True so profit/loss reporting can exclude them (guide
        Section D: "does not create revenue/expense, does not change
        profit")."""
        if (
            source_account_type == dest_account_type
            and str(source_account_id) == str(dest_account_id)
        ):
            raise TreasuryTransferError(
                "Impossible de transferer un compte vers lui-meme."
            )

        source_account = TreasuryService._lock_account(
            source_account_type, source_account_id
        )
        dest_account = TreasuryService._lock_account(
            dest_account_type, dest_account_id
        )

        common = dict(
            amount=amount, date=date, reference=reference, recorded_by=user, is_transfer=True
        )

        out_txn = TreasuryTransaction.objects.create(
            type=TreasuryTransaction.Type.MONEY_OUT,
            bank_account=source_account if source_account_type == "bank" else None,
            cash_account=source_account if source_account_type == "cash" else None,
            **common,
        )
        in_txn = TreasuryTransaction.objects.create(
            type=TreasuryTransaction.Type.MONEY_IN,
            bank_account=dest_account if dest_account_type == "bank" else None,
            cash_account=dest_account if dest_account_type == "cash" else None,
            **common,
        )
        return out_txn, in_txn

    @staticmethod
    def _lock_account(account_type, account_id):
        model = TreasuryService._ACCOUNT_MODELS.get(account_type)
        if model is None:
            raise TreasuryTransferError(
                f"Type de compte inconnu: '{account_type}' (attendu 'bank' ou 'cash')."
            )
        return model.objects.select_for_update().get(pk=account_id)


# ---------------------------------------------------------------------------
# Task 7 (client modifications plan): Shareholders / Associates domain
# ---------------------------------------------------------------------------


class ShareholderParticipationError(ValueError):
    """Raised when a shareholder's participation_percent would push the
    total across all active shareholders past 100."""


class ShareholderService:
    """Owns cross-row Shareholder invariants that can't be a single-row DB
    CheckConstraint (Task 7, client modifications plan)."""

    @staticmethod
    def validate_total_participation(candidate_percent, *, exclude_id=None) -> Decimal:
        """Sum of participation_percent across every OTHER active
        shareholder, plus `candidate_percent` (the value a create/update is
        about to set), must not exceed 100. `exclude_id` leaves the
        shareholder being updated out of the "every other" sum so its own
        current row doesn't get counted twice.

        Called from ShareholderSerializer.validate() before create/update
        of an active shareholder - inactive shareholders never count
        towards the 100 cap (their percentage isn't "in play").
        """
        existing_total = (
            Shareholder.objects.filter(is_active=True)
            .exclude(pk=exclude_id)
            .aggregate(total=Sum("participation_percent"))["total"]
            or ZERO
        )
        prospective_total = existing_total + Decimal(str(candidate_percent))
        if prospective_total > Decimal("100.00"):
            raise ShareholderParticipationError(
                f"Le total des pourcentages de participation actifs "
                f"({prospective_total}) depasserait 100."
            )
        return prospective_total


class ShareholderDistributionService:
    """Owns ShareholderProfitDistribution creation and validation (Task 7,
    client modifications plan)."""

    @staticmethod
    @transaction.atomic
    def create_distribution(
        period_start, period_end, total_profit, actor
    ) -> ShareholderProfitDistribution:
        """Create a DRAFT distribution and immediately snapshot every
        active shareholder's current participation_percent into a
        ShareholderProfitShare row (percent_snapshot), with
        amount_due = total_profit * percent_snapshot / 100, quantized to
        the cent - so a later edit to Shareholder.participation_percent can
        never retroactively change this distribution's amounts.
        """
        distribution = ShareholderProfitDistribution.objects.create(
            period_start=period_start,
            period_end=period_end,
            total_profit=total_profit,
            status=ShareholderProfitDistribution.Status.DRAFT,
            created_by=actor,
        )

        active_shareholders = Shareholder.objects.filter(is_active=True)
        for shareholder in active_shareholders:
            percent_snapshot = shareholder.participation_percent
            amount_due = (
                Decimal(str(total_profit)) * percent_snapshot / Decimal("100")
            ).quantize(Decimal("0.01"))
            ShareholderProfitShare.objects.create(
                distribution=distribution,
                shareholder=shareholder,
                percent_snapshot=percent_snapshot,
                amount_due=amount_due,
            )

        return distribution

    @staticmethod
    @transaction.atomic
    def validate_distribution(distribution_id, actor) -> ShareholderProfitDistribution:
        """Freeze a DRAFT distribution (mirrors InvoiceService.validate_invoice's
        DRAFT -> VALIDATED stamp of validated_by/validated_at)."""
        distribution = ShareholderProfitDistribution.objects.select_for_update().get(
            pk=distribution_id
        )
        if distribution.status == ShareholderProfitDistribution.Status.VALIDATED:
            return distribution

        distribution.status = ShareholderProfitDistribution.Status.VALIDATED
        distribution.validated_by = actor
        distribution.validated_at = timezone.now()
        distribution.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
        return distribution


class ShareholderWithdrawalError(ValueError):
    """Raised when a withdrawal would exceed what a shareholder is still
    owed on a specific profit share, or references data that doesn't add
    up (mismatched shareholder/share)."""


class ShareholderWithdrawalService:
    """Owns ShareholderWithdrawal creation and its treasury posting (Task 7,
    client modifications plan) - the withdrawal, the amount_withdrawn
    reconciliation on its ShareholderProfitShare (if any), and the
    TreasuryTransaction(MONEY_OUT) it must produce all happen in the same
    atomic block, under a row lock, exactly like
    FinancePostingService.record_supplier_payment_treasury.
    """

    @staticmethod
    @transaction.atomic
    def record_withdrawal(
        *,
        shareholder_id,
        amount,
        date,
        actor,
        profit_share_id=None,
        bank_account_id=None,
        cash_account_id=None,
        notes="",
    ) -> ShareholderWithdrawal:
        shareholder = Shareholder.objects.select_for_update().get(pk=shareholder_id)

        profit_share = None
        if profit_share_id is not None:
            profit_share = ShareholderProfitShare.objects.select_for_update().get(
                pk=profit_share_id
            )
            if profit_share.shareholder_id != shareholder.id:
                raise ShareholderWithdrawalError(
                    "Cette part de benefice n'appartient pas a cet actionnaire."
                )
            remaining_due = profit_share.remaining_due
            amount_decimal = Decimal(str(amount))
            if amount_decimal > remaining_due:
                raise ShareholderWithdrawalError(
                    f"Le montant du retrait ({amount_decimal}) depasse le reste "
                    f"a percevoir sur cette part ({remaining_due})."
                )

        withdrawal = ShareholderWithdrawal.objects.create(
            shareholder=shareholder,
            profit_share=profit_share,
            amount=amount,
            date=date,
            bank_account_id=bank_account_id,
            cash_account_id=cash_account_id,
            notes=notes,
            recorded_by=actor,
        )

        if profit_share is not None:
            profit_share.sync_amount_withdrawn()

        FinancePostingService.record_shareholder_withdrawal_treasury(withdrawal)

        return withdrawal


class ShareholderLedgerService:
    """Owns the per-shareholder summary view (Task 7, client modifications
    plan) - profit shares/remaining due, loans in both directions, and
    withdrawal history, in one place so the API endpoint and any future
    report compute the same numbers (same rationale as
    PaymentAllocationService.get_customer_outstanding)."""

    @staticmethod
    def get_shareholder_summary(shareholder_id) -> dict:
        shareholder = Shareholder.objects.get(pk=shareholder_id)

        shares = list(
            shareholder.profit_shares.select_related("distribution").order_by("-distribution_id")
        )
        total_amount_due = sum((s.amount_due for s in shares), ZERO)
        total_withdrawn = sum((s.amount_withdrawn for s in shares), ZERO)
        remaining_due = total_amount_due - total_withdrawn

        loans_borrowed = [
            {
                "id": loan.id,
                "lender_id": loan.lender_id,
                "lender_name": loan.lender.name,
                "amount": loan.amount,
                "amount_repaid": loan.amount_repaid,
                "remaining_amount": loan.remaining_amount,
                "status": loan.status,
                "date": loan.date,
            }
            for loan in shareholder.loans_borrowed.select_related("lender").all()
        ]
        loans_lent = [
            {
                "id": loan.id,
                "borrower_id": loan.borrower_id,
                "borrower_name": loan.borrower.name,
                "amount": loan.amount,
                "amount_repaid": loan.amount_repaid,
                "remaining_amount": loan.remaining_amount,
                "status": loan.status,
                "date": loan.date,
            }
            for loan in shareholder.loans_lent.select_related("borrower").all()
        ]
        net_loan_balance = (
            sum((loan["remaining_amount"] for loan in loans_lent), ZERO)
            - sum((loan["remaining_amount"] for loan in loans_borrowed), ZERO)
        )

        withdrawals = list(
            shareholder.withdrawals.select_related("bank_account", "cash_account", "profit_share")
            .order_by("-date", "-id")
        )

        return {
            "shareholder": {
                "id": shareholder.id,
                "name": shareholder.name,
                "participation_percent": shareholder.participation_percent,
                "is_active": shareholder.is_active,
            },
            "total_amount_due": total_amount_due,
            "total_withdrawn": total_withdrawn,
            "remaining_due": remaining_due,
            "shares": [
                {
                    "id": s.id,
                    "distribution_id": s.distribution_id,
                    "period_start": s.distribution.period_start,
                    "period_end": s.distribution.period_end,
                    "percent_snapshot": s.percent_snapshot,
                    "amount_due": s.amount_due,
                    "amount_withdrawn": s.amount_withdrawn,
                    "remaining_due": s.remaining_due,
                }
                for s in shares
            ],
            "loans_borrowed": loans_borrowed,
            "loans_lent": loans_lent,
            "net_loan_balance": net_loan_balance,
            "withdrawals": [
                {
                    "id": w.id,
                    "amount": w.amount,
                    "date": w.date,
                    "profit_share_id": w.profit_share_id,
                    "bank_account_id": w.bank_account_id,
                    "cash_account_id": w.cash_account_id,
                    "notes": w.notes,
                }
                for w in withdrawals
            ],
        }
