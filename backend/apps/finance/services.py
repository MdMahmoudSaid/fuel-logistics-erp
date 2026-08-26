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

from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    PaymentAllocation,
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
