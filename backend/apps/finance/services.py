# Financial domain services (docs/PHASE_5_PLAN.md Etape 6;
# ERP_Implementation_Experience_Guide.md Section 8.4/8.9/8.10/1.6/1.7).
#
# Payment and payment allocation are separate concerns (guide Section 8.1):
# CustomerPayment/SupplierPayment never carry an invoice FK themselves, so
# every "how much is still owed" question is answered by summing allocation
# rows here - once, so no two API paths can compute a different outstanding
# balance for the same invoice/customer (guide Section 8.4).

from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.core.request_cache import memoize_per_request
from apps.documents.models import Document
from apps.finance.models import (
    AdvanceConsumption,
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    PaymentAllocation,
    Shareholder,
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitPeriod,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    ShareholderWithdrawalAllocation,
    SupplierAdvance,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.finance.profit_periods import (
    general_expenses_paid_between,
    general_expenses_paid_total,
    latest_closed_period,
    take_snapshot,
    validated_distributions_total,
)
from apps.reports.queries.margin_report import MarginReportQuery
from apps.sales.models import Invoice
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter

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
    @memoize_per_request
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
    def get_payment_unallocated_amount(payment: CustomerPayment) -> Decimal:
        """Return the part of a receipt that is still customer credit.

        Older receipts may represent that credit either explicitly with a
        ``PaymentAllocation(invoice=None)`` row or implicitly by having no
        allocation rows at all.  Both forms are valid historical data and
        must be available to the later-allocation workflow.
        """
        prefetched = getattr(payment, "_prefetched_objects_cache", {}).get("allocations")
        if prefetched is not None:
            allocated_to_invoices = sum(
                (allocation.amount for allocation in prefetched if allocation.invoice_id), ZERO
            )
        else:
            allocated_to_invoices = (
                payment.allocations.filter(invoice__isnull=False).aggregate(total=Sum("amount"))[
                    "total"
                ]
                or ZERO
            )
        return payment.amount - allocated_to_invoices

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
                # Same rule as IndirectSettlementService: a payment only ever
                # settles invoices of its own customer, otherwise the
                # per-customer balances (and the receivable reports built on
                # them) stop reconciling with get_customer_outstanding().
                if invoice.sale.customer_id != payment.customer_id:
                    raise PaymentAllocationError(
                        f"La facture {invoice.invoice_number} n'appartient pas "
                        "au client de ce paiement."
                    )
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
    @transaction.atomic
    def allocate_available_credit(
        payment_id, invoice_allocations: list[dict]
    ) -> list[PaymentAllocation]:
        """Apply an existing receipt's unallocated credit to invoices.

        This is deliberately separate from ``allocate_payment``.  Historical
        data stores credit in two equivalent ways: as an explicit NULL-invoice
        allocation or as the unallocated remainder of the receipt.  This
        method consumes either representation without changing the receipt or
        posting treasury a second time.  Payment and invoice row locks make
        retries/concurrent submissions safe from over-allocation.
        """
        payment = CustomerPayment.objects.select_for_update().get(pk=payment_id)
        if payment.is_reversed:
            raise PaymentAllocationError("Un paiement annule ne peut pas etre affecte.")
        if not invoice_allocations:
            raise PaymentAllocationError("Ajoutez au moins une facture a affecter.")

        requested_lines: list[tuple[int, Decimal]] = []
        requested_total = ZERO
        seen_invoice_ids: set[int] = set()
        for item in invoice_allocations:
            invoice_id = item.get("invoice_id") or item.get("invoice")
            if not invoice_id:
                raise PaymentAllocationError("Une facture est requise pour chaque affectation.")
            if invoice_id in seen_invoice_ids:
                raise PaymentAllocationError("Une facture ne peut apparaitre qu'une seule fois.")
            seen_invoice_ids.add(invoice_id)

            amount = Decimal(str(item["amount"]))
            if amount <= ZERO:
                raise PaymentAllocationError("Le montant affecte doit etre strictement positif.")
            requested_lines.append((invoice_id, amount))
            requested_total += amount

        # Always acquire invoice locks in PK order.  Two receipts allocated
        # concurrently to the same pair of invoices can therefore never take
        # the locks in opposite order and deadlock.
        invoices_by_id = {
            invoice.id: invoice
            for invoice in Invoice.objects.select_for_update()
            .filter(pk__in=seen_invoice_ids)
            .order_by("pk")
        }
        if len(invoices_by_id) != len(seen_invoice_ids):
            raise PaymentAllocationError("Une des factures selectionnees est introuvable.")

        normalized: list[tuple[Invoice, Decimal]] = []
        for invoice_id, amount in requested_lines:
            invoice = invoices_by_id[invoice_id]
            if invoice.sale.customer_id != payment.customer_id:
                raise PaymentAllocationError(
                    f"La facture {invoice.invoice_number} n'appartient pas au client de ce paiement."
                )
            if invoice.status not in (
                Invoice.Status.VALIDATED,
                Invoice.Status.PARTIALLY_PAID,
            ):
                raise PaymentAllocationError(
                    f"La facture {invoice.invoice_number} n'est pas ouverte au paiement."
                )
            outstanding = PaymentAllocationService.get_invoice_outstanding(invoice)
            if amount > outstanding:
                raise PaymentAllocationError(
                    f"Le montant alloue ({amount}) depasse l'encours de la facture "
                    f"{invoice.invoice_number} ({outstanding})."
                )
            normalized.append((invoice, amount))

        available = PaymentAllocationService.get_payment_unallocated_amount(payment)
        if requested_total > available:
            raise PaymentAllocationError(
                f"Le montant a affecter ({requested_total}) depasse le credit disponible "
                f"sur ce paiement ({available})."
            )

        credit_rows = list(
            payment.allocations.select_for_update()
            .filter(invoice__isnull=True)
            .order_by("created_at", "id")
        )
        created_or_updated: list[PaymentAllocation] = []
        credit_index = 0

        for invoice, requested_amount in normalized:
            remaining = requested_amount
            while remaining > ZERO and credit_index < len(credit_rows):
                credit = credit_rows[credit_index]
                consumed = min(credit.amount, remaining)
                if consumed == credit.amount:
                    credit.invoice = invoice
                    credit.save(update_fields=["invoice", "updated_at"])
                    created_or_updated.append(credit)
                    credit_index += 1
                else:
                    credit.amount -= consumed
                    credit.save(update_fields=["amount", "updated_at"])
                    created_or_updated.append(
                        PaymentAllocation.objects.create(
                            payment=payment, invoice=invoice, amount=consumed
                        )
                    )
                remaining -= consumed

            # Any amount left here comes from the receipt's implicit
            # unallocated remainder (payment.amount minus allocation rows).
            if remaining > ZERO:
                created_or_updated.append(
                    PaymentAllocation.objects.create(
                        payment=payment, invoice=invoice, amount=remaining
                    )
                )

            PaymentAllocationService._sync_invoice_status(invoice)

        return created_or_updated

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
            # Nothing (left) paid: also the way back once every allocation
            # was reversed (e.g. a cancelled customer-paid expense).
            target = Invoice.Status.VALIDATED

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
    def record_indirect_payment(
        customer_id, expense_data: dict, actor, invoice_id=None, auto_allocate=False
    ):
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

        if auto_allocate:
            allocation = IndirectSettlementService._allocate_oldest_first(
                payment, customer, expense.amount
            )
        else:
            allocation = PaymentAllocation.objects.create(
                payment=payment, invoice=invoice, amount=expense.amount
            )
            if invoice is not None:
                PaymentAllocationService._sync_invoice_status(invoice)

        expense.indirect_settlement_payment = payment
        expense.save(update_fields=["indirect_settlement_payment", "updated_at"])

        return expense, payment, allocation


    @staticmethod
    def _allocate_oldest_first(payment, customer, amount):
        """The client's payment first reduces what he owes: his open
        (validated / partially paid) invoices, oldest first; whatever is
        left once he owes nothing more stays an unallocated credit - i.e. a
        debt of the company towards him. Returns the first allocation."""
        open_invoices = (
            Invoice.objects.select_for_update()
            .filter(
                sale__customer=customer,
                status__in=(Invoice.Status.VALIDATED, Invoice.Status.PARTIALLY_PAID),
            )
            .order_by("issued_date", "id")
        )
        remaining = amount
        allocations = []
        for invoice in open_invoices:
            if remaining <= ZERO:
                break
            outstanding = PaymentAllocationService.get_invoice_outstanding(invoice)
            if outstanding <= ZERO:
                continue
            portion = min(outstanding, remaining)
            allocations.append(
                PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=portion)
            )
            PaymentAllocationService._sync_invoice_status(invoice)
            remaining -= portion
        if remaining > ZERO:
            allocations.append(
                PaymentAllocation.objects.create(payment=payment, invoice=None, amount=remaining)
            )
        return allocations[0]

    @staticmethod
    @transaction.atomic
    def record_customer_paid_expenses(payers: list[dict], expense_data: dict, actor) -> list:
        """One general expense paid by one or several customers on the
        company's behalf (client request 2026-09-25): each payer's amount is
        deducted from what he owes; with no balance left, the amount becomes
        a company debt towards him. One Expense per payer (each reversible
        on its own), all or nothing. `payers`: [{"customer_id", "amount"}]."""
        if not payers:
            raise ValueError("Selectionnez au moins un client.")
        if len({p["customer_id"] for p in payers}) != len(payers):
            raise ValueError("Un client ne peut apparaitre qu'une seule fois.")
        results = []
        for payer in payers:
            amount = Decimal(str(payer["amount"]))
            if amount <= ZERO:
                raise ValueError("Le montant paye par chaque client doit etre positif.")
            results.append(
                IndirectSettlementService.record_indirect_payment(
                    customer_id=payer["customer_id"],
                    expense_data={**expense_data, "amount": amount},
                    actor=actor,
                    auto_allocate=True,
                )
            )
        return results


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
                invoice_ids = list(
                    payment.allocations.exclude(invoice__isnull=True)
                    .values_list("invoice", flat=True)
                    .distinct()
                )
                payment.is_reversed = True
                payment.save(update_fields=["is_reversed", "updated_at"])
                # A customer-paid expense can span several invoices.
                for invoice_id in invoice_ids:
                    PaymentAllocationService._sync_invoice_status(Invoice.objects.get(pk=invoice_id))
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
        from .commission import can_modify_commission

        payment = TransportPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == TransportPayment.Status.CANCELLED:
            raise TransportPaymentCancellationError("Ce paiement transport est deja annule.")
        if can_modify_commission(payment):
            raise TransportPaymentCancellationError(
                "Cette commission n'est pas encore reglee ; modifiez-la ou supprimez-la directement."
            )

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


class TransportPaymentCorrectionError(ValueError):
    """Raised when a TransportPayment cannot be corrected as requested."""


class TransportPaymentCorrectionService:
    """Corrects a settled commission's rate/amount in place (e.g. a wrong
    per-litre rate discovered after payment) without the cancel-then-
    recreate cycle /cancel/ would otherwise force.

    Never touches what has already physically moved (real TreasuryTransaction
    rows and AdvanceConsumption stay exactly as recorded) - it only changes
    what the trip's commission was OWED, then reclassifies the gap:

    - Owed MORE than settled so far (undercharged at the wrong rate): the
      difference becomes a normal outstanding balance, payable through the
      usual /controlled-debt-payments/ flow, same as any PARTIALLY_PAID
      commission.
    - Owed LESS than settled so far (overcharged - the client's example:
      65 F/L paid, real rate was 60 F/L): rather than trying to physically
      claw back cash the transporter already received, the payment is left
      with a *negative* remaining_amount. ControlledDebtPaymentService's
      transporter FIFO (_open_transport_payments/describe_transporter)
      already treats a negative-remaining line as money the transporter
      owes back (this is the exact mechanism an OWES-BACK TransportDeduction
      relies on, see test_transporter_balance_reflects_a_payment_the_
      transporter_owes_back) - it silently caps every future payout to that
      transporter by the excess, with no separate deduction record needed.

    Only reachable once a commission has real financial history
    (can_modify_commission() is False) - an unsettled commission should be
    edited directly (PATCH), not "corrected".
    """

    @staticmethod
    @transaction.atomic
    def correct_payment(payment: TransportPayment, changes: dict, actor, reason: str = "") -> TransportPayment:
        from .commission import can_modify_commission

        payment = TransportPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == TransportPayment.Status.CANCELLED:
            raise TransportPaymentCorrectionError(
                "Ce paiement transport est annule ; il ne peut pas etre corrige."
            )
        if can_modify_commission(payment):
            raise TransportPaymentCorrectionError(
                "Cette commission n'est pas encore reglee ; modifiez-la directement plutot que de la corriger."
            )

        content_type = ContentType.objects.get_for_model(TransportPayment)
        paid_amount = TreasuryTransaction.objects.filter(
            source_content_type=content_type,
            source_object_id=payment.id,
            type=TreasuryTransaction.Type.MONEY_OUT,
        ).aggregate(total=Sum("amount"))["total"] or ZERO
        consumed = AdvanceConsumptionService.get_consumed_amount(payment)
        settled = paid_amount + consumed

        for field, value in changes.items():
            setattr(payment, field, value)
        new_net_amount = (
            payment.base_amount - payment.deduction_amount - consumed
        ).quantize(Decimal("0.01"))
        payment.status = (
            TransportPayment.Status.PAID
            if new_net_amount == settled
            else TransportPayment.Status.PARTIALLY_PAID
        )
        payment.save(reason=reason)
        return payment


class SupplierPaymentCancellationError(ValueError):
    """Raised when a SupplierPayment cannot be cancelled as requested."""


class SupplierPaymentCancellationService:
    """Cancels a wrongly-entered SupplierPayment by contre-passation, never
    a silent edit or a hard delete (Task 6, client business decision
    confirmed 2026-09-06 - the smallest change that keeps a full audit
    trail, following the exact shape of TransportPaymentCancellationService
    and ExpensePostingService.cancel_paid_expense above: reverse whatever
    really left treasury with an offsetting entry, flag the record instead
    of deleting it, one atomic operation).

    SupplierPayment itself never triggers SupplierAdvance consumption
    (that only happens on SupplierOrder confirmation, tracked against the
    order as the AdvanceConsumption debt, not against the payment) - so
    unlike TransportPayment's cancellation there is no advance-reversal
    step needed here.
    """

    @staticmethod
    @transaction.atomic
    def cancel_supplier_payment(payment: SupplierPayment, actor) -> SupplierPayment:
        payment = SupplierPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.is_reversed:
            raise SupplierPaymentCancellationError("Ce paiement fournisseur est deja annule.")

        content_type = ContentType.objects.get_for_model(SupplierPayment)
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
                note=f"Annulation paiement fournisseur #{payment.id}",
                source_content_type=content_type,
                source_object_id=payment.id,
                recorded_by=actor,
            )

        payment.is_reversed = True
        payment.save(update_fields=["is_reversed", "updated_at"])
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
    @memoize_per_request
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
        # A confirmed order's amount can now be amended (2026-09-24): cash
        # already paid counts toward the debt like consumed advances do, so
        # it must not be covered a second time by pulling more advance; and
        # when a decrease leaves the order over-covered, every consumption is
        # released BEFORE the advances are listed (an advance fully used by
        # this order would otherwise be missing from the open list) and then
        # re-consumed oldest-first against the new total.
        cash_paid = ControlledDebtPaymentService.get_supplier_order_cash_paid(order)
        if cls.get_consumed_amount(order) + cash_paid > order.total_amount:
            cls.reverse_for_supplier_order(order)
        # Acquire locks on all open advances BEFORE computing remaining_to_cover
        advances = cls.open_supplier_advances(order.supplier, for_update=True)
        # Now compute remaining amount under lock
        remaining_to_cover = order.total_amount - cash_paid - cls.get_consumed_amount(order)
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

    _EXPENSE_CATEGORY_BY_DEBT_TYPE = {
        CUSTOMS: [Expense.Category.CUSTOMS],
        TRANSIT: [Expense.Category.TRANSIT],
        ROAD_TRANSIT: [Expense.Category.ROAD_TRANSIT],
        BORDER: [Expense.Category.ROAD],
        LOADING: [Expense.Category.LOADING],
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
    @memoize_per_request
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
    @memoize_per_request
    def get_supplier_order_cash_paid(order) -> Decimal:
        """Cash actually paid against `order`, excluding advance consumption."""
        return (
            SupplierPayment.objects.filter(
                supplier_order=order,
                is_advance=False,
            )
            # A cancelled (is_reversed=True) payment never really left
            # treasury net of its own reversal - exclude it here so the
            # order's remaining debt is restored, mirroring
            # PaymentAllocationService.get_customer_outstanding's
            # equivalent exclusion for CustomerPayment.
            .exclude(is_reversed=True)
            .aggregate(total=Sum("amount"))["total"]
            or ZERO
        )

    @staticmethod
    def _supplier_order_paid(order, *, override=None) -> Decimal:
        if override is not None:
            return override
        consumed = AdvanceConsumptionService.get_consumed_amount(order)
        return ControlledDebtPaymentService.get_supplier_order_cash_paid(order) + consumed

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
        # Bug fix (client feedback 2026-09-10): `remaining_amount` is
        # negative whenever a TransportDeduction exceeds base_amount - the
        # transporter owes the company, not the other way round (e.g. a
        # client-verification mistake produced a huge shortage deduction).
        # The old `> ZERO` filter silently dropped those lines from
        # describe_transporter/describe_transporter_balance entirely, so
        # total_due/net_balance looked as if the amount owed BACK by the
        # transporter simply didn't exist. `!= ZERO` keeps excluding a
        # truly settled (zero-balance) line while still counting a negative
        # one - _record_transport_payments' `line_amount <= ZERO: continue`
        # guard already skips negative lines safely when allocating an
        # outgoing payment, so including them here is safe for that path.
        return [
            payment
            for payment in queryset
            if cls.describe_transport_payment(payment)["remaining_amount"] != ZERO
        ]

    @classmethod
    @memoize_per_request
    def _open_expenses(cls, debt_type, *, for_update=False):
        categories = cls._EXPENSE_CATEGORY_BY_DEBT_TYPE[debt_type]
        # Every remaining bucket (CUSTOMS/TRANSIT/ROAD_TRANSIT/BORDER/
        # LOADING) maps to exactly one trip system expense category that no
        # general-expense flow can produce, so this stays allocation-
        # agnostic on purpose: a customs/transit invoice is a real, payable
        # debt before it's even split across trips (see
        # test_dashboard_summary_aggregates_customs_and_other_debts_correctly).
        queryset = Expense.objects.filter(
            category__in=categories,
            status__in=[Expense.Status.UNPAID, Expense.Status.PARTIALLY_PAID],
            paid_by_customer_directly=False,
        )
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
        # Business rule reversal (client request, 2026-09-10): the payable
        # debt to a supplier is the full confirmed order total, due
        # immediately on confirmation - not scaled by how much has been
        # physically loaded yet (that was the 2026-09-06 rule; the client
        # now wants the debt to reflect what was actually bought, with the
        # unloaded reliquat's value surfaced separately as an asset in
        # WorkingCapitalService instead - see
        # SupplierStockService.get_purchase_reliquat_amount). Example: buy
        # 200,000 L at 500 XOF/L -> debt = 100,000,000 XOF immediately, even
        # before a single truck has loaded. This total is the single source
        # of truth reused by the supplier ledger, the Dashboard's debts
        # card, Nouveau paiement's payable-debts list and
        # WorkingCapitalService (fond de roulement) - fixing it here fixes
        # all of them at once.
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
    @memoize_per_request
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
            .exclude(is_reversed=True)
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
    @memoize_per_request
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
    def describe_expense_settlement(cls, expense) -> dict:
        """total / paid / remaining of ONE expense for the general-expense
        report. Total = describe_expense()'s (sum of allocations, else the
        raw amount - never a per-litre rate). Paid: customer-paid directly =
        the whole total (no TreasuryTransaction exists for it); otherwise
        the NET of the expense's treasury payments (MONEY_OUT - MONEY_IN).
        describe_expense() itself stays untouched (payment screens)."""
        total = cls.describe_expense(expense)["total_amount"]
        if expense.paid_by_customer_directly:
            paid = total
        else:
            moves = TreasuryTransaction.objects.filter(
                source_content_type=ContentType.objects.get_for_model(Expense),
                source_object_id=expense.id,
            ).aggregate(
                out=Sum("amount", filter=Q(type=TreasuryTransaction.Type.MONEY_OUT)),
                back=Sum("amount", filter=Q(type=TreasuryTransaction.Type.MONEY_IN)),
            )
            paid = (moves["out"] or ZERO) - (moves["back"] or ZERO)
        return {"total_amount": total, "paid_amount": paid, "remaining_amount": total - paid}

    @classmethod
    @memoize_per_request
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
        }.get(debt_type, debt_type)

    @classmethod
    def _debt_type_for_expense(cls, expense):
        # None for a category with no payable-debt bucket (a general
        # expense, or a legacy trip fee in a retired category): such an
        # expense is settled on the Depenses generales page, never here.
        for debt_type, categories in cls._EXPENSE_CATEGORY_BY_DEBT_TYPE.items():
            if expense.category in categories:
                return debt_type
        return None

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


class ShareholderDistributionError(ValueError):
    """Raised when a ShareholderProfitDistribution would be created with no
    active shareholder to receive any share of it (recette bug, 2026-09-06:
    a manager was able to create AND validate a distribution while the
    Shareholder list was empty - the money was "distributed" to nobody, with
    zero ShareholderProfitShare rows ever created)."""


class ShareholderDistributionService:
    """Owns ShareholderProfitDistribution creation and validation (Task 7,
    client modifications plan)."""

    # 2026-09-08 review, point 6: a single transaction-scoped Postgres
    # advisory lock serialises every distribution mutation (create /
    # validate / cancel). The DB exclusion constraint already makes
    # overlapping active periods impossible, but two concurrent
    # validations of *different, non-overlapping* distributions could
    # still each read the same distributable_result and jointly commit
    # more than is available - this lock makes that recompute-then-write
    # sequence run one at a time. Arbitrary constant, unique to this
    # concern.
    _MUTATION_LOCK_KEY = 738_5290_11

    @staticmethod
    def _lock_mutations() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [ShareholderDistributionService._MUTATION_LOCK_KEY],
            )

    @staticmethod
    @transaction.atomic
    def create_distribution(
        period_start, period_end, total_profit, actor, period_managed=False
    ) -> ShareholderProfitDistribution:
        """Create a DRAFT distribution and immediately snapshot every
        active shareholder's current participation_percent into a
        ShareholderProfitShare row (percent_snapshot). amount_due is
        total_profit * percent_snapshot / 100, but the shares are balanced
        by the largest-remainder method so they sum to exactly
        total_profit * sum(percents) / 100 to the cent (2026-09-08 review,
        point 8) - and a later edit to Shareholder.participation_percent
        can never retroactively change this distribution's amounts.

        Raises ShareholderDistributionError before creating anything if:
        - the requested period overlaps any existing distribution whose
          status isn't CANCELLED (recette bug, 2026-09-08: the exact same
          period/benefice was distributed three times in a row with no
          guard at all - shareholders ended up "owed" the same real
          profit multiple times);
        - there is no active shareholder at all - a distribution with zero
          shares would otherwise be created (and even validated) while
          distributing nothing to nobody (recette bug, 2026-09-06).
        """
        ShareholderDistributionService._lock_mutations()

        if ShareholderProfitPeriod.objects.exists() and not period_managed:
            raise ShareholderDistributionError(
                "La repartition est creee automatiquement lors de la cloture de la periode."
            )

        if isinstance(period_start, str):
            period_start = date.fromisoformat(period_start)
        if isinstance(period_end, str):
            period_end = date.fromisoformat(period_end)

        # Fast, friendly pre-check (a clear French error instead of an
        # IntegrityError). The finance_shrdist_no_overlapping_active_period
        # exclusion constraint is the actual guarantee against a
        # concurrent create slipping through.
        overlapping_exists = (
            ShareholderProfitDistribution.objects.exclude(
                status=ShareholderProfitDistribution.Status.CANCELLED
            )
            .filter(period_start__lte=period_end, period_end__gte=period_start)
            .exists()
        )
        if overlapping_exists:
            raise ShareholderDistributionError(
                f"Une repartition existe deja pour une periode qui chevauche "
                f"{period_start} - {period_end} (statut different de Annulee) : "
                "impossible d'en creer une autre pour la meme periode."
            )

        active_shareholders = list(Shareholder.objects.filter(is_active=True))
        if not active_shareholders:
            raise ShareholderDistributionError(
                "Aucun actionnaire/associe actif : impossible de creer une "
                "repartition des benefices."
            )

        distribution = ShareholderProfitDistribution(
            period_start=period_start,
            period_end=period_end,
            total_profit=total_profit,
            status=ShareholderProfitDistribution.Status.DRAFT,
            created_by=actor,
        )
        distribution.save(user=actor)

        # 2026-09-08 review, point 8: split total_profit so the shares add
        # up to the exact target (total_profit * sum_of_percents / 100) to
        # the cent - quantizing each share independently would drop or
        # invent a centime whenever the percentages don't divide cleanly.
        # Largest-remainder method: floor every share, then hand the
        # leftover cents out one at a time to the largest fractional
        # remainders, tie-broken by shareholder id so the result is
        # deterministic and reproducible.
        total = Decimal(str(total_profit))
        percents = [sh.participation_percent for sh in active_shareholders]
        exact = [total * p / Decimal("100") for p in percents]
        target_total = (total * sum(percents) / Decimal("100")).quantize(Decimal("0.01"))
        amounts = [e.quantize(Decimal("0.01"), rounding=ROUND_DOWN) for e in exact]
        remainder_cents = int(
            ((target_total - sum(amounts)) / Decimal("0.01")).to_integral_value()
        )
        order = sorted(
            range(len(active_shareholders)),
            key=lambda i: (exact[i] - amounts[i], -active_shareholders[i].id),
            reverse=True,
        )
        step = Decimal("0.01") if remainder_cents >= 0 else Decimal("-0.01")
        for k in range(abs(remainder_cents)):
            amounts[order[k % len(order)]] += step

        for shareholder, percent_snapshot, amount_due in zip(
            active_shareholders, percents, amounts
        ):
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
        DRAFT -> VALIDATED stamp of validated_by/validated_at).

        Defense in depth alongside create_distribution's own guard: refuses
        to validate a distribution that ended up with zero
        ShareholderProfitShare rows (e.g. its only shareholder was made
        inactive after the DRAFT was created) - the exact recette bug
        (2026-09-06) was money "distributed" while validated with nobody
        to receive it.

        Hard amount block (2026-09-08 review, point 2): the source of
        truth is recomputed here, not trusted from creation time - the
        financial situation can move between drafting and validating.
        Validation is refused if total_profit exceeds the amount still
        available for distribution (ShareholderProfitPreviewService.
        get_preview()["distributable_result"]: since 2026-09-25 the total net
        profit after general expenses minus every VALIDATED distribution -
        never the debts/capital-based figure). That figure can legitimately
        be negative so the anomaly stays visible - this never clamps it - but
        no new validation may push past it.
        """
        ShareholderDistributionService._lock_mutations()
        distribution = ShareholderProfitDistribution.objects.select_for_update().get(
            pk=distribution_id
        )
        if distribution.status == ShareholderProfitDistribution.Status.VALIDATED:
            # Idempotent: repeating the action keeps the original
            # validated_by / validated_at untouched (2026-09-08 review).
            return distribution

        # 2026-09-08 review, point 3: CANCELLED is terminal. A cancelled
        # distribution can never be resurrected - the only transitions are
        # DRAFT -> VALIDATED, DRAFT -> CANCELLED, VALIDATED -> CANCELLED.
        if distribution.status == ShareholderProfitDistribution.Status.CANCELLED:
            raise ShareholderDistributionError(
                "Cette repartition est annulee : elle ne peut plus etre validee."
            )

        if not distribution.shares.exists():
            raise ShareholderDistributionError(
                "Cette repartition n'a aucune part calculee (aucun actionnaire/"
                "associe actif) : impossible de la valider."
            )

        still_distributable = ShareholderProfitPreviewService.get_preview()[
            "distributable_result"
        ]
        if distribution.total_profit > still_distributable:
            raise ShareholderDistributionError(
                f"Le benefice a repartir ({distribution.total_profit}) depasse le "
                f"montant encore disponible pour repartition "
                f"({still_distributable}) : validation impossible."
            )

        distribution.status = ShareholderProfitDistribution.Status.VALIDATED
        distribution.validated_by = actor
        distribution.validated_at = timezone.now()
        distribution.save(
            update_fields=["status", "validated_by", "validated_at", "updated_at"],
            user=actor,
        )
        return distribution

    @staticmethod
    @transaction.atomic
    def cancel_distribution(distribution_id, actor) -> ShareholderProfitDistribution:
        """Void a DRAFT or VALIDATED distribution (reverses "Task 7 ruling
        2" - see the ShareholderProfitDistribution docstring - after the
        2026-09-08 recette bug where the same real profit was distributed
        three times with no way to undo any of them).

        Refuses to cancel once a ShareholderWithdrawal has been recorded
        against one of its shares - money that has already left treasury
        for a shareholder can't be un-committed by cancelling the
        distribution behind it. Never deletes the ShareholderProfitShare
        rows (audit trail); every downstream calculation
        (ShareholderLedgerService.get_available_balance,
        ShareholderProfitPreviewService.get_preview, the dashboard's
        remaining_to_pay_shareholders) excludes a CANCELLED distribution's
        shares instead.

        Idempotent: cancelling an already-CANCELLED distribution is a
        no-op that returns it unchanged, mirroring
        validate_distribution's early return for an already-VALIDATED one.
        """
        ShareholderDistributionService._lock_mutations()
        distribution = ShareholderProfitDistribution.objects.select_for_update().get(
            pk=distribution_id
        )
        if distribution.status == ShareholderProfitDistribution.Status.CANCELLED:
            return distribution

        if ShareholderWithdrawalAllocation.objects.filter(
            profit_share__distribution_id=distribution.id
        ).exists():
            raise ShareholderDistributionError(
                "Impossible d'annuler cette repartition : au moins un retrait "
                "a deja ete effectue sur l'une de ses parts."
            )

        distribution.status = ShareholderProfitDistribution.Status.CANCELLED
        distribution.cancelled_by = actor
        distribution.cancelled_at = timezone.now()
        distribution.save(
            update_fields=["status", "cancelled_by", "cancelled_at", "updated_at"],
            user=actor,
        )
        return distribution


class ShareholderProfitPeriodError(ValueError):
    """Raised when a flexible accounting-period transition is invalid."""


class ShareholderProfitPeriodService:
    """Starts, closes and reopens user-defined profit periods atomically."""

    _MUTATION_LOCK_KEY = 738_5290_12

    @staticmethod
    def _lock_mutations() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [ShareholderProfitPeriodService._MUTATION_LOCK_KEY],
            )

    @staticmethod
    @transaction.atomic
    def open_period(start_date, actor) -> ShareholderProfitPeriod:
        ShareholderProfitPeriodService._lock_mutations()
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        # Client decision (2026-10-05): closing a period almost always ends
        # it on today's date (you close books up through now, not through
        # some already-finished day), so close_period's auto-open always
        # needs to start tomorrow. Tomorrow is a bounded, harmless amount
        # of lookahead - no financial write can land on a date before it
        # actually happens either way - so the limit allows it for manual
        # opens too instead of special-casing the automatic path.
        if start_date > timezone.localdate() + timedelta(days=1):
            raise ShareholderProfitPeriodError(
                "La date de debut ne peut pas depasser demain."
            )
        if ShareholderProfitPeriod.objects.filter(status=ShareholderProfitPeriod.Status.OPEN).exists():
            raise ShareholderProfitPeriodError("Une periode est deja ouverte.")
        latest = ShareholderProfitPeriod.objects.filter(
            status=ShareholderProfitPeriod.Status.CLOSED
        ).order_by("-end_date", "-id").first()
        if latest and start_date <= latest.end_date:
            raise ShareholderProfitPeriodError(
                f"La nouvelle periode doit commencer apres le {latest.end_date}."
            )
        period = ShareholderProfitPeriod(start_date=start_date, opened_by=actor)
        period.save(user=actor)
        return period

    @staticmethod
    @transaction.atomic
    def close_period(period_id, end_date, actor) -> ShareholderProfitPeriod:
        ShareholderProfitPeriodService._lock_mutations()
        period = ShareholderProfitPeriod.objects.select_for_update().get(pk=period_id)
        if period.status != ShareholderProfitPeriod.Status.OPEN:
            raise ShareholderProfitPeriodError("Cette periode est deja cloturee.")
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)
        if end_date < period.start_date:
            raise ShareholderProfitPeriodError("La fin de periode doit suivre son debut.")
        if end_date > timezone.localdate():
            raise ShareholderProfitPeriodError("La date de fin ne peut pas etre future.")

        preview = ShareholderProfitPreviewService.get_preview(
            date_from=period.start_date, date_to=end_date
        )
        net_profit = Decimal(preview["net_profit"]).quantize(Decimal("0.01"))
        distribution = None
        if net_profit > ZERO:
            distribution = ShareholderDistributionService.create_distribution(
                period_start=period.start_date,
                period_end=end_date,
                total_profit=net_profit,
                actor=actor,
                period_managed=True,
            )
            distribution = ShareholderDistributionService.validate_distribution(
                distribution.id, actor
            )

        period.end_date = end_date
        period.status = ShareholderProfitPeriod.Status.CLOSED
        period.net_profit = net_profit
        period.distribution = distribution
        period.closed_by = actor
        period.closed_at = timezone.now()
        # Spec 2026-10-05-periodes-independantes: freeze the running totals
        # (after this closure's own distribution) - the next period's
        # figures are measured from here, never from a date window.
        period.general_expenses_paid_snapshot = general_expenses_paid_total()
        period.distributed_total_snapshot = validated_distributions_total()
        period.save(
            update_fields=[
                "end_date", "status", "net_profit", "distribution", "closed_by",
                "closed_at", "general_expenses_paid_snapshot",
                "distributed_total_snapshot", "updated_at",
            ],
            user=actor,
        )
        take_snapshot(period, MarginReportQuery.run())

        # Client decision (2026-10-04, revised 2026-10-05): closing a
        # period must not leave operations stuck waiting for someone to
        # fill in the separate "Demarrer une nouvelle periode" form - the
        # next period starts right away. `end_date` is almost always
        # today (you close books up through now), so open_period's "at
        # most tomorrow" allowance is what makes this succeed in the
        # common case; the try/except stays only as a defensive
        # safety net since every precondition it could still fail on
        # (another OPEN period, an out-of-order start date) is already
        # impossible immediately after this close.
        try:
            ShareholderProfitPeriodService.open_period(end_date + timedelta(days=1), actor)
        except ShareholderProfitPeriodError:
            pass

        return period

    @staticmethod
    @transaction.atomic
    def reopen_period(period_id, reason, actor) -> ShareholderProfitPeriod:
        ShareholderProfitPeriodService._lock_mutations()
        reason = str(reason or "").strip()
        if len(reason) < 5:
            raise ShareholderProfitPeriodError(
                "Expliquez pourquoi cette periode doit etre rouverte."
            )
        period = ShareholderProfitPeriod.objects.select_for_update().get(pk=period_id)
        if period.status != ShareholderProfitPeriod.Status.CLOSED:
            raise ShareholderProfitPeriodError("Cette periode est deja ouverte.")
        later_exists = ShareholderProfitPeriod.objects.filter(
            status=ShareholderProfitPeriod.Status.CLOSED,
            start_date__gt=period.start_date,
        ).exists()
        if later_exists:
            raise ShareholderProfitPeriodError(
                "Seule la derniere periode cloturee peut etre rouverte."
            )
        # The only period that can still be OPEN here is the automatic
        # successor `close_period` opened right after this one - no later
        # CLOSED period exists (checked above) and the DB only ever allows
        # one OPEN period at a time, so it cannot be anything else. It has
        # no financial history of its own yet (closing is what freezes
        # net_profit/distribution), so retracting it is what frees the
        # single "one open period" slot back for `period` itself.
        current_open = ShareholderProfitPeriod.objects.select_for_update().filter(
            status=ShareholderProfitPeriod.Status.OPEN
        ).first()
        if current_open is not None:
            current_open.delete(
                user=actor,
                reason=f"Periode retiree automatiquement : reouverture de {period.start_date}.",
            )
        if period.distribution_id:
            ShareholderDistributionService.cancel_distribution(period.distribution_id, actor)

        period.trip_snapshots.all().delete()
        period.status = ShareholderProfitPeriod.Status.OPEN
        period.end_date = None
        period.net_profit = None
        period.distribution = None
        period.general_expenses_paid_snapshot = None
        period.distributed_total_snapshot = None
        period.reopened_by = actor
        period.reopened_at = timezone.now()
        period.reopen_reason = reason
        period.reopen_count += 1
        period.save(
            update_fields=[
                "status", "end_date", "net_profit", "distribution",
                "general_expenses_paid_snapshot", "distributed_total_snapshot",
                "reopened_by", "reopened_at", "reopen_reason", "reopen_count",
                "updated_at",
            ],
            user=actor,
            reason=reason,
        )
        return period


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
        bank_account_id=None,
        cash_account_id=None,
        notes="",
    ) -> ShareholderWithdrawal:
        """Automatically allocates the requested amount across the
        shareholder's own pools - all VALIDATED profit shares (oldest
        first), then, only if still short, their own capital contributions
        (oldest first) - never another shareholder's (design doc
        2026-09-15-capital-associe-retrait-design.md). Loan terms are
        never allocated against; see
        ShareholderLedgerService.get_profit_and_capital_remaining.
        """
        shareholder = Shareholder.objects.select_for_update().get(pk=shareholder_id)
        amount_decimal = Decimal(str(amount))

        available_balance = ShareholderLedgerService.get_available_balance(shareholder_id)
        if amount_decimal > available_balance:
            raise ShareholderWithdrawalError("Solde associe insuffisant.")

        allocatable = ShareholderLedgerService.get_profit_and_capital_remaining(shareholder_id)
        if amount_decimal > allocatable:
            raise ShareholderWithdrawalError("Solde associe insuffisant.")

        if bank_account_id is not None:
            account = BankAccount.objects.select_for_update().get(pk=bank_account_id)
        else:
            account = CashAccount.objects.select_for_update().get(pk=cash_account_id)
        if amount_decimal > account.current_balance:
            raise ShareholderWithdrawalError("Solde bancaire insuffisant.")

        withdrawal = ShareholderWithdrawal.objects.create(
            shareholder=shareholder,
            amount=amount,
            date=date,
            bank_account_id=bank_account_id,
            cash_account_id=cash_account_id,
            notes=notes,
            recorded_by=actor,
        )

        amount_left = amount_decimal

        shares = (
            ShareholderProfitShare.objects.select_for_update()
            .filter(
                shareholder_id=shareholder_id,
                distribution__status=ShareholderProfitDistribution.Status.VALIDATED,
            )
            .order_by("distribution__period_end", "distribution_id")
        )
        for share in shares:
            if amount_left <= 0:
                break
            remaining = share.remaining_due
            if remaining <= 0:
                continue
            consumed = min(remaining, amount_left)
            ShareholderWithdrawalAllocation.objects.create(
                withdrawal=withdrawal, profit_share=share, amount=consumed,
            )
            share.sync_amount_withdrawn()
            amount_left -= consumed

        if amount_left > 0:
            contributions = (
                ShareholderContribution.objects.select_for_update()
                .filter(shareholder_id=shareholder_id)
                .order_by("date", "id")
            )
            for contribution in contributions:
                if amount_left <= 0:
                    break
                remaining = contribution.remaining_capital
                if remaining <= 0:
                    continue
                consumed = min(remaining, amount_left)
                ShareholderWithdrawalAllocation.objects.create(
                    withdrawal=withdrawal, contribution=contribution, amount=consumed,
                )
                contribution.sync_amount_returned()
                amount_left -= consumed

        if amount_left > 0:
            # The two ceiling checks above should make this unreachable -
            # if it triggers, something upstream (e.g. a future third
            # additive term on available_balance) broke the invariant that
            # allocatable always covers a request that passed both checks.
            raise ShareholderWithdrawalError(
                "Erreur interne : montant du retrait non entierement alloue."
            )

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
    @memoize_per_request
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

    Stock fournisseur (the unloaded reliquat's monetary value) was added
    2026-09-10, alongside the debt-total business rule reversal (see
    ControlledDebtPaymentService.describe_supplier_order): now that the full
    purchase becomes a debt immediately on confirmation, the value still
    sitting unloaded at the supplier is company-owned stock, not yet in
    treasury - it is added to `total` the same way open debts are, as
    "money engaged in operations". "prets entrants" is still NOT included
    here: no reliable aggregate financial figure exists yet for it (see the
    module's git history / spec Section 3 for the reasoning) - add it later
    behind its own tested aggregate rather than approximating now.

    Bug fix (client-reported, confirmed during live recette testing,
    2026-09-14): the first cut of the reliquat asset above counted
    get_purchase_reliquat_amount() (total_amount - loaded_amount) in full,
    regardless of how much of the order had actually been paid. Since
    supplier_debt_total already books the FULL order total as an open debt
    immediately on confirmation (see describe_supplier_order), an unpaid
    order's reliquat value was the exact same money being added twice -
    once as "owed to the supplier", once as "stock we hold" - for fuel that
    hasn't cost the company a single franc yet. Example that surfaced this:
    buy 720,000 L for 532,800,000 XOF, load nothing, pay nothing ->
    supplier_debt_total=532,800,000 + supplier_reliquat_value=532,800,000
    = 1,065,600,000 added to `total` for a single, entirely unpaid
    purchase. The reliquat can only be a genuine ADDITIONAL asset once cash
    has actually left treasury for it - so it is now capped, per order, at
    min(amount actually paid to the supplier, unloaded reliquat value):
    unpaid stock stays fully represented by the open debt alone (reliquat
    contributes 0), and paid-for stock still sitting at the supplier
    contributes exactly its paid value, never more. debt + capped-reliquat
    always sums back to the order's total_amount - the same litres are
    never counted under two different labels.

    Same-day follow-up (client request, 2026-09-14): the client pointed out
    "en cours" (fuel loaded on a truck, en route) and "stock entreprise"
    (fuel that has physically arrived at the company's own depot) are the
    two later stages of the exact same pipeline the reliquat above already
    covers for the unloaded stage - purchased -> reliquat -> en cours ->
    stock entreprise -> sold (a customer receivable, tracked separately in
    customer_receivables). Leaving them out was an inconsistency, not a
    deliberate choice: paid-for fuel sitting on a truck or in the depot is
    just as real an asset as paid-for fuel still sitting at the supplier.
    See get_supplier_pipeline_breakdown() below for how the three stages
    share a single per-order "paid" budget so they can never jointly
    exceed it (the same invariant as the reliquat fix above, extended to
    three buckets instead of one). Both new stages are valued at the pure
    fuel purchase price only (order.unit_price x quantity), never the
    Dashboard's fuller "prix de revient" (+transport +customs): those extra
    costs are separate open debts already added in full via
    transporter_debt_total/other_debts, so pricing "stock entreprise" at
    cost basis here would double-count them too (client decision,
    2026-09-14, choosing the simpler basis specifically to avoid reopening
    the same class of bug on a second axis).

    Allocation-order correction (client rule, recette meeting 2026-09-24):
    the per-order paid budget is consumed company stock -> en cours ->
    reliquat, not reliquat first. The client's reading is that a payment
    first covers fuel already taken from the supplier, and only then fuel
    still sitting at the supplier; with reliquat first, a payment equal to
    the value of the fuel already loaded showed up entirely as "reliquat"
    while stock entreprise read 0. The three lines are an allocation of
    payments, not additional debts - the ordering never changes their sum.
    """

    @staticmethod
    def get_other_debts_breakdown() -> dict:
        """Splits get_working_capital()'s own `other_debts` lump sum into
        its 4 named components - added for the Benefices PDF export
        (client request 2026-09-06), which needs "douane / transit /
        transit routiere / autres frais" as separate lines rather than one
        merged figure (same grouping the Dashboard's customs_and_other
        card already uses - border+loading collapse to "other").
        get_working_capital() calls this too, so the two can never drift
        apart."""
        customs = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.CUSTOMS
        )["remaining_amount"]
        transit = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.TRANSIT
        )["remaining_amount"]
        road_transit = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.ROAD_TRANSIT
        )["remaining_amount"]
        other = sum(
            (
                ControlledDebtPaymentService.describe_expense_group(group)["remaining_amount"]
                for group in (
                    ControlledDebtPaymentService.BORDER,
                    ControlledDebtPaymentService.LOADING,
                )
            ),
            ZERO,
        )
        return {
            "customs": customs,
            "transit": transit,
            "road_transit": road_transit,
            "other": other,
        }

    @staticmethod
    @memoize_per_request
    def get_supplier_pipeline_breakdown() -> dict:
        """Per confirmed SupplierOrder, splits how much of its still-
        unsold fuel value (stocked at the depot -> en cours on a truck ->
        reliquat at the supplier) counts as a company-held asset in the Fond
        de roulement, capped IN TOTAL by what has actually been paid to
        that supplier so far - see the class docstring's 2026-09-14 entries
        for why.

        Allocation order (client rule confirmed 2026-09-24, reversing the
        2026-09-14 reliquat-first order): a payment first covers the fuel
        already taken from the supplier - company stock, then en cours -
        and only then the reliquat still sitting at the supplier. The
        order only decides which of the three lines a payment lands in:
        the total counted (and so `total`, and distributable_result which
        subtracts the same three lines back out) never depends on it.
        Sold trips stay excluded from en cours / company stock as before;
        no separate allocation rule exists for them. get_working_capital()
        calls this too, so the two can never drift apart."""
        reliquat_total = ZERO
        in_transit_total = ZERO
        company_stock_total = ZERO
        for order in SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED):
            paid_remaining = ControlledDebtPaymentService.describe_supplier_order(order)[
                "paid_amount"
            ]

            company_stock_counted = min(
                paid_remaining, SupplierStockService.get_purchase_company_stock_amount(order)
            )
            paid_remaining -= company_stock_counted

            in_transit_counted = min(
                paid_remaining, SupplierStockService.get_purchase_in_transit_amount(order)
            )
            paid_remaining -= in_transit_counted

            reliquat_counted = min(
                paid_remaining, SupplierStockService.get_purchase_reliquat_amount(order)
            )

            reliquat_total += reliquat_counted
            in_transit_total += in_transit_counted
            company_stock_total += company_stock_counted

        return {
            "supplier_reliquat_value": reliquat_total,
            "supplier_in_transit_value": in_transit_total,
            "supplier_company_stock_value": company_stock_total,
        }

    @staticmethod
    @memoize_per_request
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
        other_debts_breakdown = WorkingCapitalService.get_other_debts_breakdown()
        other_debts = sum(other_debts_breakdown.values(), ZERO)
        capital = ShareholderContributionService.get_total_capital()
        supplier_pipeline = WorkingCapitalService.get_supplier_pipeline_breakdown()
        supplier_reliquat_value = supplier_pipeline["supplier_reliquat_value"]
        supplier_in_transit_value = supplier_pipeline["supplier_in_transit_value"]
        supplier_company_stock_value = supplier_pipeline["supplier_company_stock_value"]
        gross = treasury_available + customer_receivables
        total = (
            gross
            + supplier_debt_total
            + transporter_debt_total
            + other_debts
            + supplier_reliquat_value
            + supplier_in_transit_value
            + supplier_company_stock_value
        )
        return {
            "capital": capital,
            "treasury_available": treasury_available,
            "customer_receivables": customer_receivables,
            "supplier_debt_total": supplier_debt_total,
            "transporter_debt_total": transporter_debt_total,
            "other_debts": other_debts,
            "supplier_reliquat_value": supplier_reliquat_value,
            "supplier_in_transit_value": supplier_in_transit_value,
            "supplier_company_stock_value": supplier_company_stock_value,
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
    def get_profit_and_capital_remaining(shareholder_id) -> Decimal:
        """The two pools a withdrawal can actually be allocated against -
        deliberately excludes loan terms (design doc
        2026-09-15-capital-associe-retrait-design.md): a loan between
        shareholders is never a source ShareholderWithdrawalService draws
        from, so this is a narrower, allocation-safe figure than
        get_available_balance()."""
        shares_remaining = (
            ShareholderProfitShare.objects.filter(shareholder_id=shareholder_id)
            .filter(distribution__status=ShareholderProfitDistribution.Status.VALIDATED)
            .aggregate(total=Sum(F("amount_due") - F("amount_withdrawn")))["total"]
            or ZERO
        )
        capital_remaining = (
            ShareholderContribution.objects.filter(shareholder_id=shareholder_id)
            .aggregate(total=Sum(F("amount") - F("amount_returned")))["total"]
            or ZERO
        )
        return shares_remaining + capital_remaining

    @staticmethod
    def get_available_balance(shareholder_id) -> Decimal:
        """Single source of truth for how much a shareholder can withdraw
        or lend out right now (design docs
        2026-08-26-benefices-associes-refinement-design.md and
        2026-09-15-capital-associe-retrait-design.md):

            available_balance =
                profit_share_remaining_due
              + capital_remaining
              + loans_given_remaining
              - loans_received_remaining

        Lending money to another associate is a receivable - it stays this
        shareholder's equity, just claimed via an IOU instead of sitting in
        remaining_due, so it *adds* to the balance. Receiving an advance is
        a liability that must be repaid, so it *subtracts*. Called by both
        ShareholderWithdrawalService.record_withdrawal and
        ShareholderLoanService.create_loan so a withdrawal and a loan can
        never be validated against two different numbers.

        Only a VALIDATED distribution's shares count (2026-09-08 review,
        "modele metier definitif"): a DRAFT distribution is a preparatory
        proposal with no real debt to the shareholders, and a CANCELLED one
        no longer grants any right - neither may credit an available
        balance, everywhere that balance is used.

        A shareholder's own remaining capital (design doc
        2026-09-15) is included here, but a withdrawal never allocates
        against loan terms - see get_profit_and_capital_remaining, used as
        a narrower, allocation-safe ceiling by record_withdrawal.
        """
        pools_remaining = ShareholderLedgerService.get_profit_and_capital_remaining(shareholder_id)
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
        return pools_remaining + loans_given_remaining - loans_received_remaining

    @staticmethod
    def get_balances_summary() -> dict:
        """Real, comptable balance per active shareholder (each one
        get_available_balance(), the same figure the Grand livre tab
        shows), plus the total across all of them - client request
        (2026-09-16): a card showing "la somme des soldes des
        actionnaires", distinct from ShareholderProfitPreviewService's
        indicative/forecast distributable_result shown elsewhere on the
        page."""
        shareholders = [
            {"id": s.id, "name": s.name}
            for s in Shareholder.objects.filter(is_active=True).order_by("name")
        ]
        rows = [
            {
                **s,
                "available_balance": ShareholderLedgerService.get_available_balance(s["id"]),
            }
            for s in shareholders
        ]
        total = sum((row["available_balance"] for row in rows), ZERO)
        return {"shareholders": rows, "total": total}

    @staticmethod
    def get_shareholder_summary(shareholder_id) -> dict:
        shareholder = Shareholder.objects.get(pk=shareholder_id)

        # Only VALIDATED distributions carry a real engagement to the
        # shareholder (2026-09-08 review): a DRAFT share is a preview line
        # with no financial effect, a CANCELLED one no longer grants a
        # right - neither belongs in the ledger totals nor in the
        # withdrawal-form "part de benefice" dropdown this feeds.
        shares = list(
            shareholder.profit_shares.select_related("distribution")
            .filter(distribution__status=ShareholderProfitDistribution.Status.VALIDATED)
            .order_by("-distribution_id")
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
            shareholder.withdrawals.select_related("bank_account", "cash_account")
            .prefetch_related("allocations")
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
        capital_returned = (
            shareholder.contributions.aggregate(total=Sum("amount_returned"))["total"] or ZERO
        )
        capital_remaining = total_contributed - capital_returned

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
            "capital_returned": capital_returned,
            "capital_remaining": capital_remaining,
            "withdrawals": [
                {
                    "id": w.id,
                    "amount": w.amount,
                    "date": w.date,
                    "allocations": [
                        {
                            "profit_share": a.profit_share_id,
                            "contribution": a.contribution_id,
                            "amount": a.amount,
                        }
                        for a in w.allocations.all()
                    ],
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
    @memoize_per_request
    def get_preview(date_from=None, date_to=None, since_last_closure=False) -> dict:
        # No period given -> all-time: the net profit of every trip minus
        # every validated distribution, i.e. "what is left to distribute".
        # It falls to zero once everything has been distributed (client
        # request 2026-09-25), instead of only looking at the days after the
        # last distribution's period.
        # since_last_closure ("Periode en cours", spec 2026-10-05-periodes-
        # independantes): every period-scoped figure is "now minus the last
        # closure's snapshot", so anything done after a closure - even on
        # an older trip or debt - counts in the open period.
        rows = MarginReportQuery.run(
            date_from=date_from, date_to=date_to, since_last_closure=since_last_closure
        )
        current_profit = sum((row["current_margin"] for row in rows), ZERO)
        operational_profit = current_profit
        revenue = sum((row["revenue"] for row in rows), ZERO)
        last_closure = latest_closed_period() if since_last_closure else None

        # Phase 4 (docs/superpowers/specs/2026-09-02-business-corrections-
        # 6-phases-design.md): general expenses = Expense rows with no
        # ExpenseAllocation (never a trip cost, already excluded from
        # operational_profit via MarginReportQuery/TripProfitService), only
        # those actually PAID - an UNPAID general expense hasn't left
        # treasury yet, so it shouldn't reduce net profit before it does.
        # A general expense counts when it is PAID (client decision
        # 2026-10-05), not on the date it was recorded.
        if since_last_closure:
            general_expenses_paid = general_expenses_paid_total() - (
                (last_closure.general_expenses_paid_snapshot or ZERO)
                if last_closure
                else ZERO
            )
        elif date_from or date_to:
            general_expenses_paid = general_expenses_paid_between(date_from, date_to)
        else:
            general_expenses_paid = general_expenses_paid_total()
        net_profit = operational_profit - general_expenses_paid

        # total_company_absorbed_loss is still computed for the typed API
        # contract (dashboard shareholders_summary). Since spec 2026-09-07 it
        # is no longer a distributable_result term - the customer invoice now
        # bills the received quantity, so the lower treasury already
        # integrates the absorbed loss - so it is now period-scoped like
        # every other figure in this dict.
        total_company_absorbed_loss = sum(
            (row["company_absorbed_loss_amount"] for row in rows), ZERO
        )

        # Client modifications (2026-09-04, third pass - confirmed bug
        # during actual recette testing): working_capital["total"] now ADDS
        # open debts (see WorkingCapitalService), so "resultat distribuable
        # apres dettes et capital" must subtract them back out explicitly,
        # term by term, to reach the real distributable amount - written
        # out rather than simplified so the formula stays legible if any
        # one term changes later.
        working_capital = WorkingCapitalService.get_working_capital()

        # Recette bug (2026-09-08): the same real profit was distributed
        # three times because distributable_result never subtracted what
        # had already been committed to shareholders via an earlier
        # distribution - validating a distribution never touches treasury
        # (the declarative model is intentional, see
        # ShareholderDistributionService's docstrings), so
        # working_capital["total"] still contains that money right up
        # until an actual ShareholderWithdrawal happens. already_distributed
        # is exactly the liability side of that: every VALIDATED
        # ShareholderProfitShare's still-unwithdrawn amount, company-wide,
        # not scoped by date_from/date_to (same "current outstanding
        # snapshot" contract as working_capital itself). DRAFT shares are a
        # preview only and must not move this figure (2026-09-08 review).
        already_distributed = (
            ShareholderProfitShare.objects.filter(
                distribution__status=ShareholderProfitDistribution.Status.VALIDATED
            )
            .aggregate(total=Sum(F("amount_due") - F("amount_withdrawn")))["total"]
            or ZERO
        )
        # Informational only since the 2026-09-25 client decision: the
        # amount that can be distributed to shareholders is the NET PROFIT
        # (after general expenses) of the period, not this figure. It stays
        # computed - unchanged - so the Benefices page can still show how
        # the treasury stands after debts and capital.
        result_after_debts_and_capital = (
            working_capital["total"]
            - working_capital["supplier_debt_total"]
            - working_capital["transporter_debt_total"]
            - working_capital["other_debts"]
            - working_capital["supplier_reliquat_value"]
            - working_capital["supplier_in_transit_value"]
            - working_capital["supplier_company_stock_value"]
            - working_capital["capital"]
            - already_distributed
        )

        # Client decision (2026-09-25): "bénéfice à distribuer" is ONE figure,
        # independent of debts and capital and of the period filter: every
        # trip's net profit after general expenses (all time) minus every
        # VALIDATED distribution. It falls to zero once everything has been
        # distributed. (DRAFT is a preview with no effect; CANCELLED grants
        # nothing.) The period-scoped net_profit computed above is only an
        # internal input to all_time_net_profit below - it is no longer what
        # gets returned as "net_profit" (see override right before the return,
        # client decision 2026-10-04).
        if date_from is None and date_to is None and not since_last_closure:
            all_time_net_profit = net_profit
        else:
            all_time_general_expenses = (
                Expense.objects.filter(allocations__isnull=True, status=Expense.Status.PAID)
                .aggregate(total=Sum("amount"))["total"]
                or ZERO
            )
            all_time_net_profit = (
                sum((row["current_margin"] for row in MarginReportQuery.run()), ZERO)
                - all_time_general_expenses
            )
        already_validated_total = (
            ShareholderProfitDistribution.objects.filter(
                status=ShareholderProfitDistribution.Status.VALIDATED
            ).aggregate(total=Sum("total_profit"))["total"]
            or ZERO
        )
        distributable_result = all_time_net_profit - already_validated_total

        # Reconciliation lines of the open period (spec 2026-10-05, 3.3):
        # operational_profit - general_expenses_paid + carried_over -
        # distributions_since_closure == distributable_result. A closure
        # with a negative result distributed nothing, so its deficit carries
        # over; distributions validated/cancelled since the closure close
        # the gap. Zero outside the "Periode en cours" view.
        carried_over = ZERO
        distributions_since_closure = ZERO
        if since_last_closure:
            if last_closure is not None:
                carried_over = min(last_closure.net_profit or ZERO, ZERO)
                distributions_since_closure = already_validated_total - (
                    last_closure.distributed_total_snapshot or ZERO
                )
            else:
                distributions_since_closure = already_validated_total

        # Client decision (2026-10-04): "bénéfice net après dépenses
        # générales" must behave like "bénéfice à distribuer" - it falls to
        # zero once everything has been distributed and rises again as new
        # profit accrues, on the Bénéfices page AND the dashboard - instead
        # of always showing the selected period's raw net profit regardless
        # of distributions already validated. The period-scoped value
        # computed above only served to derive all_time_net_profit.
        net_profit = distributable_result

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
            "revenue": revenue,
            "general_expenses_paid": general_expenses_paid,
            "carried_over": carried_over,
            "distributions_since_closure": distributions_since_closure,
            "net_profit": net_profit,
            "total_company_absorbed_loss": total_company_absorbed_loss,
            "working_capital": working_capital,
            "already_distributed": already_distributed,
            "all_time_net_profit": all_time_net_profit,
            "already_validated_total": already_validated_total,
            "result_after_debts_and_capital": result_after_debts_and_capital,
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
                # Business rule reversal (2026-09-10): must match
                # describe_supplier_order's debt (the full confirmed order,
                # due immediately) - otherwise this timeline entry would
                # disagree with the ledger's own summary total_due.
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

        # A cancelled payment (is_reversed=True) never really left treasury
        # net of its own reversal - excluded here so the chronological
        # ledger reads as "what's currently true"; the cancellation itself
        # (who, when, old -> new) is fully traceable in the Journal
        # d'audit, which is never filtered this way.
        payments = SupplierPayment.objects.filter(supplier=supplier, is_advance=False).exclude(
            is_reversed=True
        )
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

        # A cancelled TransportPayment never really counted - excluded here
        # (same "reads as what's currently true" rule as SupplierLedgerService
        # excluding is_reversed=True payments above) so a per-fee /cancel/
        # doesn't leave a phantom debt/payment pair behind; the cancellation
        # itself stays fully traceable in the Journal d'audit.
        payments = list(
            TransportPayment.objects.filter(transporter=transporter)
            .exclude(status=TransportPayment.Status.CANCELLED)
            .select_related("trip")
        )
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
