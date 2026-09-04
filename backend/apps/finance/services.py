# Financial domain services (docs/PHASE_5_PLAN.md Etape 6;
# ERP_Implementation_Experience_Guide.md Section 8.4/8.9/8.10/1.6/1.7).
#
# Payment and payment allocation are separate concerns (guide Section 8.1):
# CustomerPayment/SupplierPayment never carry an invoice FK themselves, so
# every "how much is still owed" question is answered by summing allocation
# rows here - once, so no two API paths can compute a different outstanding
# balance for the same invoice/customer (guide Section 8.4).

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.documents.models import Document
from apps.finance.models import (
    AdvanceConsumption,
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    PaymentAllocation,
    Shareholder,
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    SupplierAdvance,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.purchasing.models import SupplierOrder
from apps.reports.queries.margin_report import MarginReportQuery
from apps.sales.models import Invoice
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter
from apps.trips.models import Trip

ZERO = Decimal("0.00")


class PaymentAllocationError(ValueError):
    """Raised when an allocation would overdraw its payment or overpay its
    invoice."""


class PaymentAllocationService:
    """Owns CustomerPayment -> Invoice imputation (guide Section 8.3/8.4)."""

    @staticmethod
    def get_invoice_outstanding(invoice: Invoice) -> Decimal:
        # Excludes allocations whose CustomerPayment was reversed (Phase 5:
        # cancelling an indirectly-settled expense) - the PaymentAllocation
        # row itself is kept (audit trail), only its money effect stops
        # counting, same rule as get_customer_outstanding below.
        allocated = (
            invoice.allocations.exclude(payment__is_reversed=True).aggregate(total=Sum("amount"))[
                "total"
            ]
            or ZERO
        )
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
            customer.payments.exclude(is_reversed=True).aggregate(total=Sum("amount"))["total"]
            or ZERO
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

        expense.indirect_settlement_payment = payment
        expense.save(update_fields=["indirect_settlement_payment", "updated_at"])

        return expense, payment, allocation


class ExpenseCancellationError(ValueError):
    """Raised when an Expense cannot be cancelled as requested."""


class ExpensePostingService:
    """Cancels a PAID/PARTIALLY_PAID Expense (Phase 5, docs/superpowers/
    specs/2026-09-02-business-corrections-6-phases-design.md) by reversing
    it through whichever settlement path actually paid it - never a
    silent delete of a transaction that already had accounting impact,
    and never fabricating a treasury movement (bank/cash) that never
    happened for an indirect (customer-paid) settlement.
    """

    @staticmethod
    @transaction.atomic
    def cancel_paid_expense(expense: Expense, actor) -> Expense:
        expense = Expense.objects.select_for_update().get(pk=expense.pk)
        if expense.status == Expense.Status.CANCELLED:
            raise ExpenseCancellationError("Ce frais est deja annule.")
        if expense.status == Expense.Status.UNPAID:
            raise ExpenseCancellationError(
                "Ce frais n'est pas paye ; modifiez-le ou supprimez-le directement."
            )

        if expense.paid_by_customer_directly:
            # Never passed through company treasury (IndirectSettlementService
            # docstring) - reversing means undoing the synthetic CustomerPayment
            # it created to reduce the receivable, not fabricating a bank/cash
            # movement that never existed. is_reversed=True, never delete()
            # (AuditableModel blocks hard-deleting a CustomerPayment past
            # draft) - every balance/ledger consumer excludes it instead.
            payment = expense.indirect_settlement_payment
            if payment is not None and not payment.is_reversed:
                invoice = (
                    payment.allocations.exclude(invoice__isnull=True)
                    .values_list("invoice", flat=True)
                    .first()
                )
                payment.is_reversed = True
                payment.save(update_fields=["is_reversed", "updated_at"])
                if invoice is not None:
                    PaymentAllocationService._sync_invoice_status(Invoice.objects.get(pk=invoice))
        else:
            # PARTIALLY_PAID means only part of expense.amount actually left
            # treasury - reverse that real, summed amount, not expense.amount.
            content_type = ContentType.objects.get_for_model(Expense)
            paid_transactions = TreasuryTransaction.objects.filter(
                source_content_type=content_type,
                source_object_id=expense.id,
                type=TreasuryTransaction.Type.MONEY_OUT,
            )
            paid_amount = paid_transactions.aggregate(total=Sum("amount"))["total"] or ZERO
            if paid_amount > ZERO:
                original = paid_transactions.order_by("id").first()
                TreasuryTransaction.objects.create(
                    bank_account=original.bank_account,
                    cash_account=original.cash_account,
                    type=TreasuryTransaction.Type.MONEY_IN,
                    amount=paid_amount,
                    date=timezone.localdate(),
                    note=f"Annulation frais #{expense.id}",
                    source_content_type=content_type,
                    source_object_id=expense.id,
                    recorded_by=actor,
                )

        expense.status = Expense.Status.CANCELLED
        expense.save(update_fields=["status", "updated_at"])
        return expense


class TransportPaymentCancellationError(ValueError):
    """Raised when a TransportPayment cannot be cancelled as requested."""


class TransportPaymentCancellationService:
    """Cancels a TransportPayment (bug fix, 2026-09-03 recette manuelle -
    trip cancellation must reverse every financial side effect the trip
    generated). Mirrors ExpensePostingService.cancel_paid_expense's shape:
    reverses whatever really left treasury (never a flat `net_amount`,
    which can already be net of a consumed advance) and releases any
    TransporterAdvance consumption - never a silent delete of a payment
    that already had accounting impact.
    """

    @staticmethod
    @transaction.atomic
    def cancel_transport_payment(payment: TransportPayment, actor) -> TransportPayment:
        payment = TransportPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == TransportPayment.Status.CANCELLED:
            raise TransportPaymentCancellationError("Ce paiement transport est deja annule.")

        content_type = ContentType.objects.get_for_model(TransportPayment)
        paid_transactions = TreasuryTransaction.objects.filter(
            source_content_type=content_type,
            source_object_id=payment.id,
            type=TreasuryTransaction.Type.MONEY_OUT,
        )
        paid_amount = paid_transactions.aggregate(total=Sum("amount"))["total"] or ZERO
        if paid_amount > ZERO:
            original = paid_transactions.order_by("id").first()
            TreasuryTransaction.objects.create(
                bank_account=original.bank_account,
                cash_account=original.cash_account,
                type=TreasuryTransaction.Type.MONEY_IN,
                amount=paid_amount,
                date=timezone.localdate(),
                note=f"Annulation paiement transport #{payment.id}",
                source_content_type=content_type,
                source_object_id=payment.id,
                recorded_by=actor,
            )

        AdvanceConsumptionService.reverse_for_transport_payment(payment)

        payment.status = TransportPayment.Status.CANCELLED
        payment.save(update_fields=["status", "updated_at"])
        return payment


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
    def _post_treasury(
        *,
        source,
        model,
        transaction_type,
        amount,
        date,
        reference,
        recorded_by,
        resolve_accounts,
        note="",
        document=None,
    ) -> TreasuryTransaction | None:
        """Shared idempotency-check + create-under-lock body for every
        record_*_treasury() method below, in the same order the original
        three methods each had it: check source_content_type/
        source_object_id for an already-posted TreasuryTransaction FIRST
        (no-op if found, before taking any account lock), only then resolve
        + select_for_update() the account to debit/credit via the
        `resolve_accounts` callback (each caller's own account-resolution
        logic - bank vs cash, and what "neither set" means - legitimately
        differs per source model, so it stays in the caller), and finally
        create the TreasuryTransaction row. Runs inside the caller's own
        @transaction.atomic.
        """
        source_content_type = ContentType.objects.get_for_model(model)
        already_posted = TreasuryTransaction.objects.filter(
            source_content_type=source_content_type, source_object_id=source.id
        ).exists()
        if already_posted:
            return None

        bank_account, cash_account = resolve_accounts()
        if bank_account is None and cash_account is None:
            return None

        return TreasuryTransaction.objects.create(
            bank_account=bank_account,
            cash_account=cash_account,
            type=transaction_type,
            amount=amount,
            date=date,
            reference=reference,
            note=note,
            source_content_type=source_content_type,
            source_object_id=source.id,
            document=document,
            recorded_by=recorded_by,
        )

    @staticmethod
    @transaction.atomic
    def record_customer_payment_treasury(
        payment: CustomerPayment, *, document: Document | None = None
    ) -> TreasuryTransaction | None:
        """Create the one TreasuryTransaction(MONEY_IN) a direct customer
        payment must produce, linked back via source_content_type/
        source_object_id. Returns None (no-op) for an indirect payment or
        for a payment that was already posted - callers don't need to
        check either case themselves.
        """
        if payment.is_indirect:
            return None

        def resolve_accounts():
            if payment.bank_account_id:
                return (
                    BankAccount.objects.select_for_update().get(pk=payment.bank_account_id),
                    None,
                )
            if payment.cash_account_id:
                return (
                    None,
                    CashAccount.objects.select_for_update().get(pk=payment.cash_account_id),
                )
            # Neither account set on a non-indirect payment shouldn't happen
            # given CustomerPaymentSerializer.validate(), but there's
            # nothing sane to post here - stay defensive rather than raise.
            return None, None

        return FinancePostingService._post_treasury(
            source=payment,
            model=CustomerPayment,
            transaction_type=TreasuryTransaction.Type.MONEY_IN,
            amount=payment.amount,
            date=payment.payment_date,
            reference=payment.reference,
            recorded_by=payment.recorded_by,
            resolve_accounts=resolve_accounts,
            document=document,
        )

    @staticmethod
    @transaction.atomic
    def record_supplier_payment_treasury(
        payment: SupplierPayment, *, note: str = ""
    ) -> TreasuryTransaction | None:
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

        def resolve_accounts():
            if payment.bank_account_id:
                return (
                    BankAccount.objects.select_for_update().get(pk=payment.bank_account_id),
                    None,
                )
            if payment.cash_account_id:
                return (
                    None,
                    CashAccount.objects.select_for_update().get(pk=payment.cash_account_id),
                )
            # Neither account set shouldn't happen given the DB-level
            # finance_supplierpayment_requires_account constraint, but
            # there's nothing sane to post here - stay defensive rather
            # than raise.
            return None, None

        return FinancePostingService._post_treasury(
            source=payment,
            model=SupplierPayment,
            transaction_type=TreasuryTransaction.Type.MONEY_OUT,
            amount=payment.amount,
            date=payment.payment_date,
            reference=payment.reference,
            recorded_by=payment.recorded_by,
            resolve_accounts=resolve_accounts,
            note=note,
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

        def resolve_accounts():
            if withdrawal.bank_account_id:
                return (
                    BankAccount.objects.select_for_update().get(pk=withdrawal.bank_account_id),
                    None,
                )
            if withdrawal.cash_account_id:
                return (
                    None,
                    CashAccount.objects.select_for_update().get(pk=withdrawal.cash_account_id),
                )
            # Neither account set shouldn't happen given the DB-level
            # finance_shareholderwithdrawal_requires_account constraint, but
            # there's nothing sane to post here - stay defensive rather
            # than raise.
            return None, None

        return FinancePostingService._post_treasury(
            source=withdrawal,
            model=ShareholderWithdrawal,
            transaction_type=TreasuryTransaction.Type.MONEY_OUT,
            amount=withdrawal.amount,
            date=withdrawal.date,
            reference="",
            recorded_by=withdrawal.recorded_by,
            resolve_accounts=resolve_accounts,
        )


class AdvanceConsumptionService:
    """Consumes open SupplierAdvance/TransporterAdvance rows, oldest-first,
    against a real debt (a confirmed SupplierOrder or a TransportPayment) -
    the automatic counterpart to ControlledDebtPaymentService's FIFO payment
    allocation, but for advances instead of bank payments (docs/superpowers/
    specs/2026-08-31-supplier-transporter-advances-design.md).

    Never creates a TreasuryTransaction: consuming an advance is a pure
    accounting compensation, the cash already left the company when the
    advance itself was created.
    """

    @classmethod
    def open_supplier_advances(cls, supplier, *, for_update=False) -> list:
        queryset = SupplierAdvance.objects.filter(supplier=supplier).order_by("date", "id")
        if for_update:
            queryset = queryset.select_for_update()
        return [advance for advance in queryset if advance.remaining_amount > ZERO]

    @classmethod
    def open_transporter_advances(cls, transporter, *, for_update=False) -> list:
        queryset = TransporterAdvance.objects.filter(transporter=transporter).order_by("date", "id")
        if for_update:
            queryset = queryset.select_for_update()
        return [advance for advance in queryset if advance.remaining_amount > ZERO]

    @staticmethod
    def get_consumed_amount(debt) -> Decimal:
        content_type = ContentType.objects.get_for_model(debt.__class__)
        return (
            AdvanceConsumption.objects.filter(
                debt_content_type=content_type, debt_object_id=debt.id, reversed_at__isnull=True
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )

    @classmethod
    @transaction.atomic
    def consume_for_supplier_order(cls, order) -> None:
        """Idempotent: safe to call more than once for the same order - it
        always recomputes what's still uncovered before consuming further,
        so a redundant call (or a resave of an already-CONFIRMED order)
        never double-consumes an advance. Locks advances before computing
        remaining_to_cover to prevent concurrent double-consumption."""
        if order.status != order.Status.CONFIRMED:
            return
        content_type = ContentType.objects.get_for_model(order.__class__)
        # Acquire locks on all open advances BEFORE computing remaining_to_cover
        advances = cls.open_supplier_advances(order.supplier, for_update=True)
        # Now compute remaining amount under lock
        remaining_to_cover = order.total_amount - cls.get_consumed_amount(order)
        if remaining_to_cover <= ZERO:
            return
        for advance in advances:
            if remaining_to_cover <= ZERO:
                break
            amount = min(advance.remaining_amount, remaining_to_cover)
            if amount <= ZERO:
                continue
            AdvanceConsumption.objects.create(
                supplier_advance=advance,
                debt_content_type=content_type,
                debt_object_id=order.id,
                amount=amount,
            )
            remaining_to_cover -= amount

    @classmethod
    @transaction.atomic
    def reverse_for_supplier_order(cls, order) -> None:
        """Undo every non-reversed consumption this order made, restoring
        the advance(s) it used to open (design doc: reversed_at rather than
        a deletion, for a full audit trail)."""
        content_type = ContentType.objects.get_for_model(order.__class__)
        AdvanceConsumption.objects.filter(
            debt_content_type=content_type, debt_object_id=order.id, reversed_at__isnull=True
        ).update(reversed_at=timezone.now())

    @classmethod
    @transaction.atomic
    def reverse_for_transport_payment(cls, payment) -> None:
        """Same as reverse_for_supplier_order, for a TransportPayment -
        bug fix (2026-09-03 recette manuelle): cancelling a Trip must
        release any TransporterAdvance its TransportPayment consumed
        (consume_for_transport_payment runs unconditionally on save(), so
        even a never-paid PLANNED payment can already hold a consumption).
        Called by TransportPaymentCancellationService.cancel_transport_payment."""
        content_type = ContentType.objects.get_for_model(payment.__class__)
        AdvanceConsumption.objects.filter(
            debt_content_type=content_type, debt_object_id=payment.id, reversed_at__isnull=True
        ).update(reversed_at=timezone.now())

    @classmethod
    @transaction.atomic
    def consume_for_transport_payment(cls, payment) -> Decimal:
        """Returns the total now consumed (non-reversed) for this payment,
        for TransportPayment.save() to fold into net_amount directly.
        Locks advances before computing remaining_to_cover to prevent
        concurrent double-consumption."""
        content_type = ContentType.objects.get_for_model(payment.__class__)
        target = payment.base_amount - payment.deduction_amount
        # Acquire locks on all open advances BEFORE computing remaining_to_cover
        advances = cls.open_transporter_advances(payment.transporter, for_update=True)
        # Now compute remaining amount under lock
        remaining_to_cover = target - cls.get_consumed_amount(payment)
        if remaining_to_cover > ZERO:
            for advance in advances:
                if remaining_to_cover <= ZERO:
                    break
                amount = min(advance.remaining_amount, remaining_to_cover)
                if amount <= ZERO:
                    continue
                AdvanceConsumption.objects.create(
                    transporter_advance=advance,
                    debt_content_type=content_type,
                    debt_object_id=payment.id,
                    amount=amount,
                )
                remaining_to_cover -= amount
        return cls.get_consumed_amount(payment)


class AdvanceError(ValueError):
    """Raised when an advance request breaks a financial rule (open debt
    already exists, insufficient treasury balance, invalid amount)."""


class AdvanceService:
    """Creates a SupplierAdvance/TransporterAdvance and posts its immediate
    treasury outflow, atomically (docs/superpowers/specs/2026-08-31-
    supplier-transporter-advances-design.md). Consuming an advance never
    goes through here - only AdvanceConsumptionService does that, and it
    never touches treasury."""

    @staticmethod
    def _lock_account(*, bank_account_id, cash_account_id):
        if bank_account_id:
            return BankAccount.objects.select_for_update().get(pk=bank_account_id), None
        return None, CashAccount.objects.select_for_update().get(pk=cash_account_id)

    @staticmethod
    def _check_balance(bank_account, cash_account, amount):
        account = bank_account or cash_account
        if amount > account.current_balance:
            raise AdvanceError("Solde insuffisant pour verser cette avance.")

    @classmethod
    @transaction.atomic
    def create_supplier_advance(
        cls, *, supplier_id, bank_account_id, cash_account_id, amount, date,
        reference, notes, attachment, actor,
    ) -> SupplierAdvance:
        supplier = Supplier.objects.select_for_update().get(pk=supplier_id)
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise AdvanceError("Le montant de l'avance doit etre superieur a zero.")

        net_balance = ControlledDebtPaymentService.describe_supplier_balance(supplier)["net_balance"]
        if net_balance < ZERO:
            raise AdvanceError(
                "Impossible de creer une avance : ce fournisseur a une dette ouverte reelle."
            )

        bank_account, cash_account = cls._lock_account(
            bank_account_id=bank_account_id, cash_account_id=cash_account_id
        )
        cls._check_balance(bank_account, cash_account, amount)

        advance = SupplierAdvance.objects.create(
            supplier=supplier, bank_account=bank_account, cash_account=cash_account,
            amount=amount, date=date, reference=reference, notes=notes, recorded_by=actor,
        )
        document = None
        if attachment:
            document = Document.objects.create(
                file=attachment, document_type="supplier_advance_proof", reference=reference,
                uploaded_by=actor, content_type=ContentType.objects.get_for_model(SupplierAdvance),
                object_id=advance.id,
            )
            advance.document = document
            advance.save(update_fields=["document", "updated_at"])
        TreasuryTransaction.objects.create(
            bank_account=bank_account, cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_OUT, amount=amount, date=date,
            reference=reference, note=notes,
            source_content_type=ContentType.objects.get_for_model(SupplierAdvance),
            source_object_id=advance.id, document=document, recorded_by=actor,
        )
        return advance

    @classmethod
    @transaction.atomic
    def create_transporter_advance(
        cls, *, transporter_id, bank_account_id, cash_account_id, amount, date,
        reference, notes, attachment, actor,
    ) -> TransporterAdvance:
        transporter = Transporter.objects.select_for_update().get(pk=transporter_id)
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise AdvanceError("Le montant de l'avance doit etre superieur a zero.")

        net_balance = ControlledDebtPaymentService.describe_transporter_balance(transporter)["net_balance"]
        if net_balance < ZERO:
            raise AdvanceError(
                "Impossible de creer une avance : ce transporteur a une dette ouverte reelle."
            )

        bank_account, cash_account = cls._lock_account(
            bank_account_id=bank_account_id, cash_account_id=cash_account_id
        )
        cls._check_balance(bank_account, cash_account, amount)

        advance = TransporterAdvance.objects.create(
            transporter=transporter, bank_account=bank_account, cash_account=cash_account,
            amount=amount, date=date, reference=reference, notes=notes, recorded_by=actor,
        )
        document = None
        if attachment:
            document = Document.objects.create(
                file=attachment, document_type="transporter_advance_proof", reference=reference,
                uploaded_by=actor, content_type=ContentType.objects.get_for_model(TransporterAdvance),
                object_id=advance.id,
            )
            advance.document = document
            advance.save(update_fields=["document", "updated_at"])
        TreasuryTransaction.objects.create(
            bank_account=bank_account, cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_OUT, amount=amount, date=date,
            reference=reference, note=notes,
            source_content_type=ContentType.objects.get_for_model(TransporterAdvance),
            source_object_id=advance.id, document=document, recorded_by=actor,
        )
        return advance


class ControlledDebtPaymentError(ValueError):
    """Raised when a controlled debt payment request breaks a financial rule."""


class ControlledDebtPaymentService:
    """Bank-only outgoing payments tied to an existing payable debt."""

    SUPPLIER = "supplier"
    TRANSPORTER = "transporter"
    CUSTOMS = "customs"
    TRANSIT = "transit"
    ROAD_TRANSIT = "road_transit"
    BORDER = "border"
    LOADING = "loading"
    TRIP_OTHER = "trip_other"

    _EXPENSE_CATEGORY_BY_DEBT_TYPE = {
        CUSTOMS: [Expense.Category.CUSTOMS],
        TRANSIT: [Expense.Category.TRANSIT],
        ROAD_TRANSIT: [Expense.Category.ROAD_TRANSIT],
        BORDER: [Expense.Category.ROAD],
        LOADING: [Expense.Category.LOADING],
        TRIP_OTHER: [
            Expense.Category.UNLOADING,
            Expense.Category.ADMINISTRATION,
            Expense.Category.RENT,
            Expense.Category.SALARY,
            Expense.Category.REPAIRS,
            Expense.Category.BANK_CHARGES,
            Expense.Category.OTHER,
        ],
    }

    @classmethod
    def supported_debt_types(cls):
        return [
            cls.SUPPLIER,
            cls.TRANSPORTER,
            cls.CUSTOMS,
            cls.TRANSIT,
            cls.ROAD_TRANSIT,
            cls.BORDER,
            cls.LOADING,
            cls.TRIP_OTHER,
        ]

    @classmethod
    def get_payable_debts(cls, debt_type) -> list[dict]:
        if debt_type == cls.SUPPLIER:
            rows = []
            supplier_ids = (
                SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)
                .values_list("supplier_id", flat=True)
                .distinct()
            )
            for supplier in Supplier.objects.filter(id__in=supplier_ids).order_by("name", "id"):
                row = cls.describe_supplier(supplier)
                if row["remaining_amount"] > ZERO:
                    rows.append(row)
            return rows

        if debt_type == cls.TRANSPORTER:
            rows = []
            transporter_ids = (
                TransportPayment.objects.exclude(status=TransportPayment.Status.PAID)
                .values_list("transporter_id", flat=True)
                .distinct()
            )
            for transporter in Transporter.objects.filter(id__in=transporter_ids).order_by("name", "id"):
                row = cls.describe_transporter(transporter)
                if row["remaining_amount"] > ZERO:
                    rows.append(row)
            return rows

        categories = cls._EXPENSE_CATEGORY_BY_DEBT_TYPE.get(debt_type)
        if categories is None:
            raise ControlledDebtPaymentError("Type de dette inconnu.")

        row = cls.describe_expense_group(debt_type)
        return [row] if row["remaining_amount"] > ZERO else []

    @classmethod
    @transaction.atomic
    def record_payment(
        cls,
        *,
        debt_type,
        debt_id,
        bank_account_id,
        amount,
        date,
        reference,
        actor,
        note="",
        attachment=None,
    ) -> dict:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise ControlledDebtPaymentError("Le montant a payer doit etre superieur a zero.")

        bank_account = BankAccount.objects.select_for_update().get(pk=bank_account_id)
        bank_balance = bank_account.current_balance
        if amount > bank_balance:
            raise ControlledDebtPaymentError(
                "Solde bancaire insuffisant pour effectuer ce paiement."
            )

        if debt_type == cls.SUPPLIER:
            result = cls._record_supplier_payments(
                debt_id=debt_id,
                bank_account=bank_account,
                amount=amount,
                date=date,
                reference=reference,
                actor=actor,
                note=note,
            )
        elif debt_type == cls.TRANSPORTER:
            result = cls._record_transport_payments(
                debt_id=debt_id,
                bank_account=bank_account,
                amount=amount,
                date=date,
                reference=reference,
                actor=actor,
                note=note,
            )
        elif debt_type in cls._EXPENSE_CATEGORY_BY_DEBT_TYPE:
            result = cls._record_expense_payments(
                debt_type=debt_type,
                debt_id=debt_id,
                bank_account=bank_account,
                amount=amount,
                date=date,
                reference=reference,
                actor=actor,
                note=note,
            )
        else:
            raise ControlledDebtPaymentError("Type de dette inconnu.")

        if attachment is not None and result["transactions"]:
            document = Document.objects.create(
                file=attachment,
                document_type="treasury_payment_proof",
                reference=reference,
                uploaded_by=actor,
                content_type=ContentType.objects.get_for_model(TreasuryTransaction),
                object_id=result["transactions"][0].id,
            )
            # Set on each in-memory instance (not just the DB row via a bulk
            # update) so the response this call returns - which serializes
            # these same objects - already reflects the attachment.
            for txn in result["transactions"]:
                txn.document = document
                txn.save(update_fields=["document"])

        result["bank_balance_before"] = bank_balance
        result["bank_balance_after"] = bank_balance - amount
        return result

    @classmethod
    def _record_supplier_payments(
        cls, *, debt_id, bank_account, amount, date, reference, actor, note=""
    ):
        supplier = Supplier.objects.select_for_update().get(pk=debt_id)
        debt = cls.describe_supplier(supplier)
        cls._validate_remaining(amount, debt["remaining_amount"])

        remaining_to_allocate = amount
        payments = []
        transactions = []
        for order in cls._open_supplier_orders(supplier, for_update=True):
            if remaining_to_allocate <= ZERO:
                break
            line = cls.describe_supplier_order(order)
            line_amount = min(remaining_to_allocate, line["remaining_amount"])
            if line_amount <= ZERO:
                continue
            payment = SupplierPayment.objects.create(
                supplier=supplier,
                supplier_order=order,
                amount=line_amount,
                payment_date=date,
                method=SupplierPayment.Method.BANK_TRANSFER,
                bank_account=bank_account,
                is_advance=False,
                reference=reference,
                recorded_by=actor,
            )
            transaction_obj = FinancePostingService.record_supplier_payment_treasury(
                payment, note=note
            )
            payments.append(payment)
            if transaction_obj is not None:
                transactions.append(transaction_obj)
            remaining_to_allocate -= line_amount

        if remaining_to_allocate > ZERO:
            raise ControlledDebtPaymentError("Aucune dette fournisseur ouverte suffisante.")

        return {
            "transaction": transactions[0] if transactions else None,
            "transactions": transactions,
            "sources": payments,
            "debt": cls.describe_supplier(supplier),
            "remaining_after": debt["remaining_amount"] - amount,
        }

    @classmethod
    def _record_transport_payments(
        cls, *, debt_id, bank_account, amount, date, reference, actor, note=""
    ):
        transporter = Transporter.objects.select_for_update().get(pk=debt_id)
        debt = cls.describe_transporter(transporter)
        cls._validate_remaining(amount, debt["remaining_amount"])

        remaining_to_allocate = amount
        transactions = []
        for payment in cls._open_transport_payments(transporter, for_update=True):
            if remaining_to_allocate <= ZERO:
                break
            line = cls.describe_transport_payment(payment)
            line_amount = min(remaining_to_allocate, line["remaining_amount"])
            if line_amount <= ZERO:
                continue
            transaction_obj = cls._create_debt_transaction(
                debt=payment,
                bank_account=bank_account,
                amount=line_amount,
                date=date,
                reference=reference,
                actor=actor,
                note=note,
            )
            transactions.append(transaction_obj)
            cls._sync_transport_status(payment)
            remaining_to_allocate -= line_amount

        if remaining_to_allocate > ZERO:
            raise ControlledDebtPaymentError("Aucune dette transporteur ouverte suffisante.")

        return {
            "transaction": transactions[0] if transactions else None,
            "transactions": transactions,
            "debt": cls.describe_transporter(transporter),
            "remaining_after": debt["remaining_amount"] - amount,
        }

    @classmethod
    def _record_expense_payments(
        cls, *, debt_type, debt_id, bank_account, amount, date, reference, actor, note=""
    ):
        if debt_id != 0:
            raise ControlledDebtPaymentError("Cette dette doit etre payee au niveau du groupe.")
        debt = cls.describe_expense_group(debt_type)
        cls._validate_remaining(amount, debt["remaining_amount"])

        remaining_to_allocate = amount
        transactions = []
        for expense in cls._open_expenses(debt_type, for_update=True):
            if remaining_to_allocate <= ZERO:
                break
            line = cls.describe_expense(expense)
            line_amount = min(remaining_to_allocate, line["remaining_amount"])
            if line_amount <= ZERO:
                continue
            transaction_obj = cls._create_debt_transaction(
                debt=expense,
                bank_account=bank_account,
                amount=line_amount,
                date=date,
                reference=reference,
                actor=actor,
                note=note,
            )
            transactions.append(transaction_obj)
            cls._sync_expense_status(expense)
            remaining_to_allocate -= line_amount

        if remaining_to_allocate > ZERO:
            raise ControlledDebtPaymentError("Aucune dette de frais ouverte suffisante.")

        return {
            "transaction": transactions[0] if transactions else None,
            "transactions": transactions,
            "debt": cls.describe_expense_group(debt_type),
            "remaining_after": debt["remaining_amount"] - amount,
        }

    @staticmethod
    def _validate_remaining(amount, remaining):
        if amount > remaining:
            raise ControlledDebtPaymentError(
                f"Le montant a payer ({amount}) depasse le reste a payer ({remaining})."
            )

    @staticmethod
    def _create_debt_transaction(*, debt, bank_account, amount, date, reference, actor, note=""):
        return TreasuryTransaction.objects.create(
            bank_account=bank_account,
            type=TreasuryTransaction.Type.MONEY_OUT,
            amount=amount,
            note=note,
            date=date,
            reference=reference,
            source_content_type=ContentType.objects.get_for_model(debt.__class__),
            source_object_id=debt.id,
            recorded_by=actor,
        )

    @staticmethod
    def _paid_for_source(model, object_id) -> Decimal:
        content_type = ContentType.objects.get_for_model(model)
        return (
            TreasuryTransaction.objects.filter(
                source_content_type=content_type,
                source_object_id=object_id,
                type=TreasuryTransaction.Type.MONEY_OUT,
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )

    @staticmethod
    def _supplier_order_paid(order, *, override=None) -> Decimal:
        if override is not None:
            return override
        payments = (
            SupplierPayment.objects.filter(
                supplier_order=order,
                is_advance=False,
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        consumed = AdvanceConsumptionService.get_consumed_amount(order)
        return payments + consumed

    @classmethod
    def _open_supplier_orders(cls, supplier, *, for_update=False):
        queryset = (
            SupplierOrder.objects.filter(
                supplier=supplier,
                status=SupplierOrder.Status.CONFIRMED,
            )
            .select_related("supplier")
            .order_by("purchase_date", "id")
        )
        if for_update:
            queryset = queryset.select_for_update()
        return [
            order
            for order in queryset
            if cls.describe_supplier_order(order)["remaining_amount"] > ZERO
        ]

    @classmethod
    def _open_transport_payments(cls, transporter, *, for_update=False):
        queryset = (
            TransportPayment.objects.filter(transporter=transporter)
            .exclude(status__in=[TransportPayment.Status.PAID, TransportPayment.Status.CANCELLED])
            .select_related("trip", "transporter")
            .order_by("created_at", "id")
        )
        if for_update:
            queryset = queryset.select_for_update()
        return [
            payment
            for payment in queryset
            if cls.describe_transport_payment(payment)["remaining_amount"] > ZERO
        ]

    @classmethod
    def _open_expenses(cls, debt_type, *, for_update=False):
        categories = cls._EXPENSE_CATEGORY_BY_DEBT_TYPE[debt_type]
        queryset = Expense.objects.filter(
            category__in=categories,
            status__in=[Expense.Status.UNPAID, Expense.Status.PARTIALLY_PAID],
            paid_by_customer_directly=False,
        )
        if debt_type == cls.TRIP_OTHER:
            # Bug fix (2026-09-03 recette manuelle): TRIP_OTHER is the only
            # bucket whose category list (UNLOADING/ADMINISTRATION/RENT/
            # SALARY/REPAIRS/BANK_CHARGES/OTHER, plus any custom category
            # via _debt_type_for_expense's fallback) overlaps with plain
            # general-expense categories from the Depenses generales page.
            # CUSTOMS/TRANSIT/ROAD_TRANSIT/BORDER/LOADING stay
            # allocation-agnostic on purpose (a customs/transit invoice is
            # a real, payable debt before it's even split across trips -
            # see test_dashboard_summary_aggregates_customs_and_other_debts_correctly).
            # Only TRIP_OTHER needs a Trip ExpenseAllocation to prove it's
            # actually a trip fee and not a general company expense (Loyer,
            # Internet, ...) that happens to share a category with it.
            #
            # pk__in=<subquery> rather than a plain allocations__content_type
            # filter: an Expense split across several trips has several
            # ExpenseAllocation rows, and joining directly would duplicate
            # it in the result - .distinct() can't be combined with
            # select_for_update() (for_update=True below), which Postgres
            # rejects outright ("FOR UPDATE is not allowed with DISTINCT").
            trip_allocated_expense_ids = ExpenseAllocation.objects.filter(
                content_type=ContentType.objects.get_for_model(Trip)
            ).values_list("expense_id", flat=True)
            queryset = queryset.filter(pk__in=trip_allocated_expense_ids)
        queryset = queryset.prefetch_related("allocations").order_by("date", "id")
        if for_update:
            queryset = queryset.select_for_update()
        return [
            expense
            for expense in queryset
            if cls.describe_expense(expense)["remaining_amount"] > ZERO
        ]

    @classmethod
    def describe_supplier(cls, supplier) -> dict:
        lines = [cls.describe_supplier_order(order) for order in cls._open_supplier_orders(supplier)]
        total = sum((line["total_amount"] for line in lines), ZERO)
        paid = sum((line["paid_amount"] for line in lines), ZERO)
        return {
            "id": supplier.id,
            "debt_type": cls.SUPPLIER,
            "label": supplier.name,
            "total_amount": total,
            "paid_amount": paid,
            "remaining_amount": total - paid,
            "status": "PARTIALLY_PAID" if paid > ZERO else "UNPAID",
            "lines": lines,
        }

    @classmethod
    def describe_supplier_order(cls, order, *, paid_amount=None) -> dict:
        paid = cls._supplier_order_paid(order, override=paid_amount)
        total = order.total_amount if order.status == SupplierOrder.Status.CONFIRMED else ZERO
        return {
            "id": order.id,
            "debt_type": cls.SUPPLIER,
            "label": f"{order.reference} - {order.supplier.name}",
            "total_amount": total,
            "paid_amount": paid,
            "remaining_amount": total - paid,
            "status": order.status,
        }

    @classmethod
    def describe_transporter(cls, transporter) -> dict:
        lines = [
            cls.describe_transport_payment(payment)
            for payment in cls._open_transport_payments(transporter)
        ]
        total = sum((line["total_amount"] for line in lines), ZERO)
        paid = sum((line["paid_amount"] for line in lines), ZERO)
        return {
            "id": transporter.id,
            "debt_type": cls.TRANSPORTER,
            "label": transporter.name,
            "total_amount": total,
            "paid_amount": paid,
            "remaining_amount": total - paid,
            "status": "PARTIALLY_PAID" if paid > ZERO else "UNPAID",
            "lines": lines,
        }

    @classmethod
    def describe_supplier_balance(cls, supplier) -> dict:
        total_due = cls.describe_supplier(supplier)["remaining_amount"]
        open_advances = sum(
            (advance.remaining_amount for advance in AdvanceConsumptionService.open_supplier_advances(supplier)),
            ZERO,
        )
        last_advance = (
            SupplierAdvance.objects.filter(supplier=supplier)
            .order_by("-date", "-id").values("date", "amount").first()
        )
        last_payment = (
            SupplierPayment.objects.filter(supplier=supplier, is_advance=False)
            .order_by("-payment_date", "-id").values("payment_date", "amount").first()
        )
        return {
            "id": supplier.id,
            "label": supplier.name,
            "total_due": total_due,
            "open_advances": open_advances,
            "net_balance": open_advances - total_due,
            "last_advance": (
                {"date": last_advance["date"], "amount": last_advance["amount"]}
                if last_advance else None
            ),
            "last_payment": (
                {"date": last_payment["payment_date"], "amount": last_payment["amount"]}
                if last_payment else None
            ),
        }

    @classmethod
    def describe_transporter_balance(cls, transporter) -> dict:
        total_due = cls.describe_transporter(transporter)["remaining_amount"]
        open_advances = sum(
            (
                advance.remaining_amount
                for advance in AdvanceConsumptionService.open_transporter_advances(transporter)
            ),
            ZERO,
        )
        last_advance = (
            TransporterAdvance.objects.filter(transporter=transporter)
            .order_by("-date", "-id").values("date", "amount").first()
        )
        last_payment_txn = (
            TreasuryTransaction.objects.filter(
                source_content_type=ContentType.objects.get_for_model(TransportPayment),
                source_object_id__in=TransportPayment.objects.filter(
                    transporter=transporter
                ).values_list("id", flat=True),
                type=TreasuryTransaction.Type.MONEY_OUT,
            ).order_by("-date", "-id").values("date", "amount").first()
        )
        return {
            "id": transporter.id,
            "label": transporter.name,
            "total_due": total_due,
            "open_advances": open_advances,
            "net_balance": open_advances - total_due,
            "last_advance": (
                {"date": last_advance["date"], "amount": last_advance["amount"]}
                if last_advance else None
            ),
            "last_payment": (
                {"date": last_payment_txn["date"], "amount": last_payment_txn["amount"]}
                if last_payment_txn else None
            ),
        }

    @classmethod
    def describe_transport_payment(cls, payment) -> dict:
        paid = cls._paid_for_source(TransportPayment, payment.id)
        return {
            "id": payment.id,
            "debt_type": cls.TRANSPORTER,
            "label": f"{payment.trip.reference} - {payment.transporter.name}",
            "total_amount": payment.net_amount,
            "paid_amount": paid,
            "remaining_amount": payment.net_amount - paid,
            "status": payment.status,
        }

    @classmethod
    def describe_expense_group(cls, debt_type) -> dict:
        lines = [cls.describe_expense(expense) for expense in cls._open_expenses(debt_type)]
        total = sum((line["total_amount"] for line in lines), ZERO)
        paid = sum((line["paid_amount"] for line in lines), ZERO)
        return {
            "id": 0,
            "debt_type": debt_type,
            "label": cls._expense_group_label(debt_type),
            "total_amount": total,
            "paid_amount": paid,
            "remaining_amount": total - paid,
            "status": "PARTIALLY_PAID" if paid > ZERO else "UNPAID",
            "lines": lines,
        }

    @classmethod
    def describe_expense(cls, expense) -> dict:
        paid = cls._paid_for_source(Expense, expense.id)
        allocations = list(expense.allocations.all())
        trip_labels = [
            allocation.content_object.reference
            for allocation in allocations
            if getattr(allocation.content_object, "reference", None)
        ]
        label_suffix = f" - {', '.join(trip_labels)}" if trip_labels else ""
        # Bug fix (2026-09-03 recette manuelle): expense.amount is the raw
        # input value - for a PER_LITRE trip fee that's the XOF/L rate, not
        # the total (TripCostService/ExpenseSerializer._resolve_allocated_amount
        # already compute the real total into ExpenseAllocation.allocated_amount
        # at creation time, exactly for this reason). A debt/payable-debt
        # total must always be the sum of what's actually allocated - only
        # falls back to expense.amount for a not-yet-allocated expense
        # (e.g. a customs invoice recorded before being split across
        # trips), which has no allocations to sum in the first place.
        allocated_total = sum((a.allocated_amount for a in allocations), ZERO)
        total_amount = allocated_total if allocations else expense.amount
        return {
            "id": expense.id,
            "debt_type": cls._debt_type_for_expense(expense),
            "label": f"{expense.get_category_display()} {expense.date}{label_suffix}",
            "total_amount": total_amount,
            "paid_amount": paid,
            "remaining_amount": total_amount - paid,
            "status": expense.status,
        }

    @classmethod
    def _expense_group_label(cls, debt_type):
        return {
            cls.CUSTOMS: "Douane",
            cls.TRANSIT: "Transit",
            cls.ROAD_TRANSIT: "Transit routiere",
            cls.BORDER: "Frontiere",
            cls.LOADING: "Chargement",
            cls.TRIP_OTHER: "Autres frais du trajet",
        }.get(debt_type, debt_type)

    @classmethod
    def _debt_type_for_expense(cls, expense):
        for debt_type, categories in cls._EXPENSE_CATEGORY_BY_DEBT_TYPE.items():
            if expense.category in categories:
                return debt_type
        return cls.TRIP_OTHER

    @classmethod
    def _sync_transport_status(cls, payment):
        remaining = cls.describe_transport_payment(payment)["remaining_amount"]
        if remaining <= ZERO:
            status = TransportPayment.Status.PAID
        elif remaining < payment.net_amount:
            status = TransportPayment.Status.PARTIALLY_PAID
        else:
            status = payment.status
        if status != payment.status:
            payment.status = status
            payment.save(update_fields=["status", "updated_at"])

    @classmethod
    def _sync_expense_status(cls, expense):
        # Bug fix (2026-09-03 recette manuelle): remaining_amount and
        # total_amount must come from the same describe_expense() call -
        # comparing the (now correctly allocation-aware) remaining_amount
        # against the raw expense.amount broke PARTIALLY_PAID detection
        # for a PER_LITRE/PER_TRUCK trip fee (e.g. Transit at 10 XOF/L: a
        # 50 000 XOF partial payment against a 100 000 XOF real total left
        # `remaining (50 000) < expense.amount (10)` False, so the status
        # never left UNPAID).
        described = cls.describe_expense(expense)
        remaining = described["remaining_amount"]
        total_amount = described["total_amount"]
        if remaining <= ZERO:
            status = Expense.Status.PAID
        elif remaining < total_amount:
            status = Expense.Status.PARTIALLY_PAID
        else:
            status = expense.status
        if status != expense.status:
            expense.status = status
            expense.save(update_fields=["status", "updated_at"])


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
        amount_decimal = Decimal(str(amount))

        # Unconditional balance checks (design doc
        # 2026-08-26-benefices-associes-refinement-design.md, Fix 1): before
        # this, a withdrawal without a profit_share_id skipped every
        # balance check, and even a profit_share-tied withdrawal never
        # checked the destination account - a shareholder could withdraw an
        # arbitrary amount regardless of what they were actually owed or
        # what the bank/cash account actually held.
        available_balance = ShareholderLedgerService.get_available_balance(shareholder_id)
        if amount_decimal > available_balance:
            raise ShareholderWithdrawalError("Solde associe insuffisant.")

        if bank_account_id is not None:
            account = BankAccount.objects.select_for_update().get(pk=bank_account_id)
        else:
            account = CashAccount.objects.select_for_update().get(pk=cash_account_id)
        if amount_decimal > account.current_balance:
            raise ShareholderWithdrawalError("Solde bancaire insuffisant.")

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


class ShareholderContributionError(ValueError):
    """Raised when a capital contribution has an invalid account
    selection or amount. The proof image is optional (Task 13, 2026-09-04
    recette corrections: no justificatif/document is ever mandatory)."""


class ShareholderContributionService:
    """Owns ShareholderContribution creation (Phase 1, docs/superpowers/
    specs/2026-09-02-business-corrections-6-phases-design.md) - copied
    from AdvanceService.create_supplier_advance's shape (Document +
    TreasuryTransaction created directly, in one atomic block) rather than
    ShareholderWithdrawalService's (which delegates posting to
    FinancePostingService._post_treasury). The proof document is optional
    (Task 13, 2026-09-04 recette corrections), same as an advance's
    attachment.
    """

    @staticmethod
    @transaction.atomic
    def record_contribution(
        *,
        shareholder_id,
        amount,
        date,
        actor,
        attachment,
        bank_account_id=None,
        cash_account_id=None,
        reference="",
        notes="",
    ) -> ShareholderContribution:
        if bank_account_id and cash_account_id:
            raise ShareholderContributionError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account_id and not cash_account_id:
            raise ShareholderContributionError("Un compte de tresorerie (banque ou caisse) est requis.")

        shareholder = Shareholder.objects.select_for_update().get(pk=shareholder_id)
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= ZERO:
            raise ShareholderContributionError("Le montant de l'apport doit etre superieur a zero.")

        bank_account = None
        cash_account = None
        if bank_account_id:
            bank_account = BankAccount.objects.select_for_update().get(pk=bank_account_id)
        else:
            cash_account = CashAccount.objects.select_for_update().get(pk=cash_account_id)

        contribution = ShareholderContribution.objects.create(
            shareholder=shareholder, bank_account=bank_account, cash_account=cash_account,
            amount=amount, date=date, reference=reference, notes=notes, recorded_by=actor,
        )
        document = None
        if attachment:
            document = Document.objects.create(
                file=attachment, document_type="shareholder_contribution_proof", reference=reference,
                uploaded_by=actor, content_type=ContentType.objects.get_for_model(ShareholderContribution),
                object_id=contribution.id,
            )
            contribution.document = document
            contribution.save(update_fields=["document", "updated_at"])
        TreasuryTransaction.objects.create(
            bank_account=bank_account, cash_account=cash_account,
            type=TreasuryTransaction.Type.MONEY_IN, amount=amount, date=date,
            reference=reference, note=notes,
            source_content_type=ContentType.objects.get_for_model(ShareholderContribution),
            source_object_id=contribution.id, document=document, recorded_by=actor,
        )
        return contribution

    @staticmethod
    def get_total_capital() -> Decimal:
        opening_balances = Shareholder.objects.aggregate(total=Sum("contribution"))["total"] or ZERO
        contributions = ShareholderContribution.objects.aggregate(total=Sum("amount"))["total"] or ZERO
        return opening_balances + contributions


class WorkingCapitalService:
    """Fond de roulement client (docs/superpowers/specs/2026-09-04-recette-
    corrections-design.md, Section 3) - a management indicator, NOT the
    accounting fonds de roulement. Correction (2026-09-04, third pass -
    confirmed bug during actual client recette testing, reverting the
    second pass's subtraction which was itself a misreading): open debts
    are ADDED, not subtracted -
      gross = treasury_available + customer_receivables
      total = gross + supplier_debt_total + transporter_debt_total + other_debts
    Example confirmed with the client: gross 300,000,000 + dettes
    fournisseurs 45,000,000 + dettes transporteurs 2,925,000 + dettes
    douane/transit/frais 10,255,000 = 358,180,000. Everywhere else (party
    balances, ledgers, payment screens) a debt stays displayed as an amount
    owed, unaffected by this indicator - only here does an open debt
    increase the figure (mass of funds engaged in operations). Never a
    source of payment - payments always draw from real BankAccount/
    CashAccount.

    Stock fournisseur / commandes en cours and "prets entrants" are in the
    client's spreadsheet but are intentionally NOT included here: no
    reliable aggregate financial figure exists yet for either (see the
    module's git history / spec Section 3 for the reasoning) - add them
    later behind their own tested aggregate rather than approximating now.
    """

    @staticmethod
    def get_working_capital() -> dict:
        # Local import: apps.reports.queries.customer_outstanding_report
        # imports PaymentAllocationService from this very module - a
        # module-level import here would create a circular import the
        # first time either module loads before the other finishes.
        from apps.reports.queries.customer_outstanding_report import (
            CustomerOutstandingReportQuery,
        )

        treasury_available = sum(
            (a.current_balance for a in BankAccount.objects.filter(is_active=True)), ZERO
        ) + sum(
            (a.current_balance for a in CashAccount.objects.filter(is_active=True)), ZERO
        )
        customer_receivables = sum(
            (row["outstanding"] for row in CustomerOutstandingReportQuery.run()), ZERO
        )
        supplier_debt_total = sum(
            (
                ControlledDebtPaymentService.describe_supplier_balance(s)["total_due"]
                for s in Supplier.objects.filter(is_active=True)
            ),
            ZERO,
        )
        transporter_debt_total = sum(
            (
                ControlledDebtPaymentService.describe_transporter_balance(t)["total_due"]
                for t in Transporter.objects.filter(is_active=True)
            ),
            ZERO,
        )
        other_debts = sum(
            (
                ControlledDebtPaymentService.describe_expense_group(group)["remaining_amount"]
                for group in (
                    ControlledDebtPaymentService.CUSTOMS,
                    ControlledDebtPaymentService.TRANSIT,
                    ControlledDebtPaymentService.ROAD_TRANSIT,
                    ControlledDebtPaymentService.BORDER,
                    ControlledDebtPaymentService.LOADING,
                    ControlledDebtPaymentService.TRIP_OTHER,
                )
            ),
            ZERO,
        )
        capital = ShareholderContributionService.get_total_capital()
        gross = treasury_available + customer_receivables
        total = gross + supplier_debt_total + transporter_debt_total + other_debts
        return {
            "capital": capital,
            "treasury_available": treasury_available,
            "customer_receivables": customer_receivables,
            "supplier_debt_total": supplier_debt_total,
            "transporter_debt_total": transporter_debt_total,
            "other_debts": other_debts,
            "gross": gross,
            "total": total,
        }


class ShareholderLoanError(ValueError):
    """Raised when a loan's principal exceeds what the lender has
    available, or a repayment increment is invalid or would push
    amount_repaid past the loan's principal."""


class ShareholderLoanService:
    """Owns ShareholderLoan creation and repayment recording (Task 7,
    client modifications plan - fix for the loan-repayment lost-update
    race; design doc 2026-08-26-benefices-associes-refinement-design.md
    Fix 2 for creation).

    A client PATCHing an absolute `amount_repaid` it computed from its own
    stale read (current + entered increment) can silently overwrite a
    concurrent repayment from another tab/user - the second write just
    replaces the first with no error. record_repayment() instead takes
    only the INCREMENT and applies it under select_for_update(), the same
    row-lock pattern ShareholderWithdrawalService.record_withdrawal() and
    PaymentAllocationService.allocate_payment() already use for the same
    reason: two concurrent requests must not be able to jointly clobber
    each other's effect on the same row.
    """

    @staticmethod
    @transaction.atomic
    def create_loan(*, borrower_id, lender_id, amount, date, notes="") -> ShareholderLoan:
        """Create an advance/debt between two associates. Deliberately
        creates only the ShareholderLoan row - money moving between
        shareholders never touches company treasury (the model docstring's
        invariant), so unlike ShareholderWithdrawalService.record_withdrawal
        this never calls FinancePostingService and never creates a
        TreasuryTransaction. The lender is row-locked and checked against
        ShareholderLedgerService.get_available_balance so a loan can never
        commit the lender past what they actually have available."""
        lender = Shareholder.objects.select_for_update().get(pk=lender_id)
        amount_decimal = Decimal(str(amount))

        available_balance = ShareholderLedgerService.get_available_balance(lender.id)
        if amount_decimal > available_balance:
            raise ShareholderLoanError("Solde disponible du preteur insuffisant.")

        return ShareholderLoan.objects.create(
            borrower_id=borrower_id,
            lender_id=lender.id,
            amount=amount_decimal,
            date=date,
            notes=notes,
        )

    @staticmethod
    @transaction.atomic
    def record_repayment(loan_id, increment_amount) -> ShareholderLoan:
        loan = ShareholderLoan.objects.select_for_update().get(pk=loan_id)

        try:
            increment = Decimal(str(increment_amount))
        except (InvalidOperation, TypeError, ValueError):
            raise ShareholderLoanError("Montant invalide.")
        if increment <= 0:
            raise ShareholderLoanError("Le montant du remboursement doit etre positif.")

        new_total = loan.amount_repaid + increment
        if new_total > loan.amount:
            raise ShareholderLoanError(
                f"Ce remboursement porterait le total rembourse ({new_total}) "
                f"au-dela du principal ({loan.amount})."
            )

        loan.amount_repaid = new_total
        loan.save(update_fields=["amount_repaid", "status", "updated_at"])
        return loan


class ShareholderLedgerService:
    """Owns the per-shareholder summary view (Task 7, client modifications
    plan) - profit shares/remaining due, loans in both directions, and
    withdrawal history, in one place so the API endpoint and any future
    report compute the same numbers (same rationale as
    PaymentAllocationService.get_customer_outstanding)."""

    @staticmethod
    def get_available_balance(shareholder_id) -> Decimal:
        """Single source of truth for how much a shareholder can withdraw
        or lend out right now (design doc
        2026-08-26-benefices-associes-refinement-design.md):

            available_balance =
                profit_share_remaining_due
              + loans_given_remaining
              - loans_received_remaining

        Lending money to another associate is a receivable - it stays this
        shareholder's equity, just claimed via an IOU instead of sitting in
        remaining_due, so it *adds* to the balance. Receiving an advance is
        a liability that must be repaid, so it *subtracts*. Called by both
        ShareholderWithdrawalService.record_withdrawal and
        ShareholderLoanService.create_loan so a withdrawal and a loan can
        never be validated against two different numbers.
        """
        shares_remaining = (
            ShareholderProfitShare.objects.filter(shareholder_id=shareholder_id).aggregate(
                total=Sum(F("amount_due") - F("amount_withdrawn"))
            )["total"]
            or ZERO
        )
        loans_given_remaining = sum(
            (loan.remaining_amount for loan in ShareholderLoan.objects.filter(lender_id=shareholder_id)),
            ZERO,
        )
        loans_received_remaining = sum(
            (
                loan.remaining_amount
                for loan in ShareholderLoan.objects.filter(borrower_id=shareholder_id)
            ),
            ZERO,
        )
        return shares_remaining + loans_given_remaining - loans_received_remaining

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

        # Bug fix (2026-09-03 recette manuelle): a ShareholderContribution
        # (Phase 1) was only ever visible via its TreasuryTransaction - the
        # Associes page had no way to show what a given shareholder had
        # actually put into the company. Deliberately kept out of
        # total_amount_due/remaining_due/available_balance above: capital
        # is not distributable profit (see ShareholderContribution model
        # docstring). The detailed history itself is fetched separately by
        # the frontend from GET /api/shareholder-contributions/?shareholder=
        # (already exists, already serializes proof_url/accounts/etc.) -
        # total_contributed here is just the one aggregate this summary
        # needs to show alongside remaining_due/available_balance.
        total_contributed = (
            shareholder.contributions.aggregate(total=Sum("amount"))["total"] or ZERO
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
            "available_balance": ShareholderLedgerService.get_available_balance(shareholder_id),
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
            "total_contributed": total_contributed,
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


class ShareholderProfitPreviewService:
    """Read-only, indicative profit preview (design doc
    2026-08-26-benefices-associes-refinement-design.md) - never stored,
    never creates a ShareholderProfitDistribution/ShareholderProfitShare,
    and never feeds into ShareholderLedgerService.get_available_balance.
    Delegates every cost/margin number to the existing profit engine
    (MarginReportQuery -> TripProfitService) instead of recomputing margin
    here, same rule Task 8's margin report already follows.
    """

    @staticmethod
    def get_preview(date_from=None, date_to=None) -> dict:
        if date_from is None and date_to is None:
            last_validated = (
                ShareholderProfitDistribution.objects.filter(
                    status=ShareholderProfitDistribution.Status.VALIDATED
                )
                .order_by("-period_end")
                .first()
            )
            if last_validated is not None:
                date_from = last_validated.period_end + timedelta(days=1)

        rows = MarginReportQuery.run(date_from=date_from, date_to=date_to)
        current_profit = sum((row["current_margin"] for row in rows), ZERO)
        operational_profit = current_profit

        # Phase 4 (docs/superpowers/specs/2026-09-02-business-corrections-
        # 6-phases-design.md): general expenses = Expense rows with no
        # ExpenseAllocation (never a trip cost, already excluded from
        # operational_profit via MarginReportQuery/TripProfitService), only
        # those actually PAID - an UNPAID general expense hasn't left
        # treasury yet, so it shouldn't reduce net profit before it does.
        general_expenses = Expense.objects.filter(
            allocations__isnull=True, status=Expense.Status.PAID
        )
        if date_from:
            general_expenses = general_expenses.filter(date__gte=date_from)
        if date_to:
            general_expenses = general_expenses.filter(date__lte=date_to)
        general_expenses_paid = (
            general_expenses.aggregate(total=Sum("amount"))["total"] or ZERO
        )
        net_profit = operational_profit - general_expenses_paid

        # Client modifications (2026-09-04, third pass - confirmed bug
        # during actual recette testing): working_capital["total"] now ADDS
        # open debts (see WorkingCapitalService), so "resultat distribuable
        # apres dettes et capital" must subtract them back out explicitly,
        # term by term, to reach the real distributable amount - written
        # out rather than simplified so the formula stays legible if any
        # one term changes later.
        working_capital = WorkingCapitalService.get_working_capital()
        distributable_result = (
            working_capital["total"]
            - working_capital["supplier_debt_total"]
            - working_capital["transporter_debt_total"]
            - working_capital["other_debts"]
            - working_capital["capital"]
        )

        # Business decision (2026-09-04, distribution basis change): a
        # shareholder's indicative share is now based on distributable_result,
        # not net_profit - net_profit measures operating profitability, but
        # the amount actually available to distribute must also account for
        # open debts, capital already contributed, and available treasury/
        # receivables (see distributable_result above). net_profit stays
        # computed and returned unchanged (still the "is the business
        # profitable" figure), it just no longer feeds this share. Still
        # never feeds ShareholderProfitDistribution directly - only the
        # distribution form's suggested default (frontend) does that, and
        # the distribution itself always uses whatever total_profit the
        # user actually submits.
        shareholders = [
            {
                "shareholder_id": shareholder.id,
                "name": shareholder.name,
                "participation_percent": shareholder.participation_percent,
                "indicative_share": (
                    distributable_result * shareholder.participation_percent / Decimal("100")
                ).quantize(Decimal("0.01")),
            }
            for shareholder in Shareholder.objects.filter(is_active=True)
        ]

        return {
            "period_start": date_from,
            "period_end": date_to,
            "current_profit": current_profit,
            "operational_profit": operational_profit,
            "general_expenses_paid": general_expenses_paid,
            "net_profit": net_profit,
            "working_capital": working_capital,
            "distributable_result": distributable_result,
            "shareholders": shareholders,
        }


class SupplierLedgerService:
    """Chronological Grand livre for one supplier: advances given, debts
    created, advances consumed, and complementary payments, all in one
    ordered timeline (docs/superpowers/specs/2026-08-31-supplier-
    transporter-advances-design.md) - built on describe_supplier_balance so
    the summary cards never disagree with Nouveau paiement/Dashboard."""

    @staticmethod
    def get_ledger(supplier) -> dict:
        entries = []

        for advance in SupplierAdvance.objects.filter(supplier=supplier):
            entries.append({
                "type": "advance_given",
                "date": advance.date,
                "amount": advance.amount,
                "reference": advance.reference,
                "note": advance.notes,
                "proof_url": (
                    advance.document.file.url
                    if advance.document_id and advance.document.file else None
                ),
            })

        orders = SupplierOrder.objects.filter(supplier=supplier, status=SupplierOrder.Status.CONFIRMED)
        for order in orders:
            entries.append({
                "type": "debt_created",
                "date": order.purchase_date,
                "amount": order.total_amount,
                "reference": order.reference,
                "note": "",
                "proof_url": None,
            })

        order_ct = ContentType.objects.get_for_model(SupplierOrder)
        consumptions = AdvanceConsumption.objects.filter(
            supplier_advance__supplier=supplier, debt_content_type=order_ct, reversed_at__isnull=True,
        ).select_related("supplier_advance")
        for consumption in consumptions:
            # Dated to the debt it was applied against (not the consumption
            # row's own created_at) - a consumption always takes effect on
            # the same business timeline as the debt that triggered it, and
            # purchase_date can be arbitrarily backdated relative to when
            # the order was actually confirmed in the system.
            entries.append({
                "type": "advance_consumed",
                "date": consumption.debt_object.purchase_date,
                "amount": consumption.amount,
                "reference": consumption.supplier_advance.reference,
                "note": "",
                "proof_url": None,
            })

        payments = SupplierPayment.objects.filter(supplier=supplier, is_advance=False)
        payment_ct = ContentType.objects.get_for_model(SupplierPayment)
        for payment in payments:
            txn = (
                TreasuryTransaction.objects.filter(
                    source_content_type=payment_ct, source_object_id=payment.id, document__isnull=False,
                ).select_related("document").order_by("-date", "-id").first()
            )
            entries.append({
                "type": "payment",
                "date": payment.payment_date,
                "amount": payment.amount,
                "reference": payment.reference,
                "note": "",
                "proof_url": txn.document.file.url if txn and txn.document.file else None,
            })

        entries.sort(key=lambda entry: entry["date"])

        return {
            "summary": ControlledDebtPaymentService.describe_supplier_balance(supplier),
            "entries": entries,
        }


class TransporterLedgerService:
    """Same chronological Grand livre as SupplierLedgerService, for
    transporters - 'debt_created' entries come from TransportPayment
    (base_amount - deduction_amount, before any advance consumption),
    'payment' entries from the TreasuryTransaction rows
    ControlledDebtPaymentService posts against each TransportPayment."""

    @staticmethod
    def get_ledger(transporter) -> dict:
        entries = []

        for advance in TransporterAdvance.objects.filter(transporter=transporter):
            entries.append({
                "type": "advance_given",
                "date": advance.date,
                "amount": advance.amount,
                "reference": advance.reference,
                "note": advance.notes,
                "proof_url": (
                    advance.document.file.url
                    if advance.document_id and advance.document.file else None
                ),
            })

        payments = list(TransportPayment.objects.filter(transporter=transporter).select_related("trip"))
        for payment in payments:
            entries.append({
                "type": "debt_created",
                "date": payment.created_at.date(),
                "amount": payment.base_amount - payment.deduction_amount,
                "reference": payment.trip.reference,
                "note": "",
                "proof_url": None,
            })

        payment_ct = ContentType.objects.get_for_model(TransportPayment)
        consumptions = AdvanceConsumption.objects.filter(
            transporter_advance__transporter=transporter, debt_content_type=payment_ct,
            reversed_at__isnull=True,
        ).select_related("transporter_advance")
        for consumption in consumptions:
            # Dated to the debt it was applied against, same rationale as
            # SupplierLedgerService above (consistency, not just here - a
            # TransportPayment's own "debt_created" entry uses its
            # created_at too, so this keeps both dated the same way).
            entries.append({
                "type": "advance_consumed",
                "date": consumption.debt_object.created_at.date(),
                "amount": consumption.amount,
                "reference": consumption.transporter_advance.reference,
                "note": "",
                "proof_url": None,
            })

        payment_ids = [payment.id for payment in payments]
        treasury_rows = TreasuryTransaction.objects.filter(
            source_content_type=payment_ct, source_object_id__in=payment_ids,
            type=TreasuryTransaction.Type.MONEY_OUT,
        ).select_related("document")
        for txn in treasury_rows:
            entries.append({
                "type": "payment",
                "date": txn.date,
                "amount": txn.amount,
                "reference": txn.reference,
                "note": txn.note,
                "proof_url": txn.document.file.url if txn.document_id and txn.document.file else None,
            })

        entries.sort(key=lambda entry: entry["date"])

        return {
            "summary": ControlledDebtPaymentService.describe_transporter_balance(transporter),
            "entries": entries,
        }
