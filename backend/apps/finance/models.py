from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import models

from apps.audit.mixins import AuditableModel
from apps.core.models import TimeStampedModel
from apps.core.request_cache import memoize_per_request

CURRENCY_CHOICES = [("XOF", "XOF")]


@memoize_per_request
def _account_current_balance(account):
    """opening_balance + Sigma(TreasuryTransaction) (guide Section 8.10/D:
    "computed, never stored, so it can never drift from the transaction
    ledger"). A plain module function rather than a queryset method on
    TreasuryTransaction, since it needs to run from both BankAccount and
    CashAccount and TreasuryTransaction is defined later in this file.
    """
    money_in = (
        account.transactions.filter(type=TreasuryTransaction.Type.MONEY_IN).aggregate(
            total=models.Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    money_out = (
        account.transactions.filter(type=TreasuryTransaction.Type.MONEY_OUT).aggregate(
            total=models.Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    return Decimal(account.opening_balance) + money_in - money_out


class BankAccount(TimeStampedModel):
    name = models.CharField(max_length=150)
    bank_name = models.CharField(max_length=150, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="XOF")
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def current_balance(self):
        return _account_current_balance(self)


class CashAccount(TimeStampedModel):
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=150, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="XOF")
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def current_balance(self):
        return _account_current_balance(self)


class TransportDeduction(AuditableModel, TimeStampedModel):
    """Deduction on a transporter's account for chargeable (out-of-tolerance)
    loss on a trip (docs/PHASE_4_PLAN.md Etape 3;
    ERP_Implementation_Experience_Guide.md Section 7.5).

    A separate transaction row rather than a mutation of the trip's
    transport cost, so the transporter ledger keeps a full audit trail:
    "transport earned - deductions - advances - payments = outstanding"
    (guide Section 7.5) never collapses into a single opaque number.

    `unit_price` is CONFIRMED (client, 2026-09-06) to be the customer's
    sale price for the trip, not the supplier's purchase cost - see
    apps.trips.services.DeliveryService.sync_transport_shortage_deduction,
    the sole writer of this field. This is a deliberate business rule, not
    a bug: do not change it without an explicit new client instruction.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        CANCELLED = "CANCELLED", "Cancelled"

    trip = models.ForeignKey(
        "trips.Trip", on_delete=models.PROTECT, related_name="transport_deductions"
    )
    transporter = models.ForeignKey(
        "transport.Transporter",
        on_delete=models.PROTECT,
        related_name="deductions",
    )
    chargeable_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    amount = models.DecimalField(max_digits=16, decimal_places=2, editable=False)
    currency = models.CharField(max_length=10, default="XOF")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(chargeable_quantity__gt=0),
                name="finance_transportdeduction_chargeable_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="finance_transportdeduction_unit_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Deduction for {self.trip.reference}: {self.chargeable_quantity} L"

    def is_locked_for_deletion(self) -> bool:
        return self.status != self.Status.DRAFT

    def save(self, *args, **kwargs):
        self.amount = (self.chargeable_quantity * self.unit_price).quantize(
            Decimal("0.01")
        )
        super().save(*args, **kwargs)


class CustomerPayment(AuditableModel, TimeStampedModel):
    """Money received from a customer (docs/PHASE_5_PLAN.md Etape 1;
    ERP_Implementation_Experience_Guide.md Section 8.2/1.7).

    Deliberately carries no invoice FK: which invoice(s) it settles, if any,
    is recorded by PaymentAllocation rows instead, so one payment can cover
    one invoice, several invoices, or remain unallocated credit (guide
    Section 8.3 - "do not force one payment per invoice").

    bank_account/cash_account mirror the pair TreasuryTransaction will use
    (Etape 5): nullable=True here rather than one GenericRelation, since
    "must be null when is_indirect=True, otherwise exactly one of the two
    is required" is a business rule enforced by the Etape 7 serializer, not
    a DB-level concern beyond "never both at once".
    """

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"
        OTHER = "OTHER", "Other"

    class Destination(models.TextChoices):
        """Where a direct payment lands, or that it's not direct at all
        (Task 4, client modifications plan). Deliberately kept alongside
        `is_indirect`/`bank_account`/`cash_account` rather than replacing
        them: those fields already have real consumers (serializer
        exclusivity validation, filterset_fields, IndirectSettlementService).
        `destination` only exists to disambiguate a real cash account from
        the dedicated "Vers moi" placeholder for treasury-posting purposes -
        CustomerPaymentSerializer.validate() derives is_indirect/bank_account/
        cash_account FROM this field, so the two stay consistent by
        construction rather than by client discipline.
        """

        BANK = "BANK", "Banque"
        CASH = "CASH", "Caisse"
        VERS_MOI = "VERS_MOI", "Vers moi"
        INDIRECT = "INDIRECT", "Indirect"

    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices)
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="customer_payments"
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="customer_payments"
    )
    reference = models.CharField(max_length=100, blank=True)
    is_indirect = models.BooleanField(default=False)
    destination = models.CharField(max_length=20, choices=Destination.choices, default=Destination.CASH)
    # Recorded with "Nouvelle avance" (customer owed nothing): listed in the
    # ledger's own "Avances" section instead of "Paiements" (2026-10-11).
    is_advance = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="customer_payments_recorded"
    )
    # Set by ExpensePostingService.cancel_paid_expense (Phase 5) when
    # reversing an indirect settlement's synthetic payment - never a hard
    # delete (AuditableModel.is_locked_for_deletion blocks that once past
    # draft), so every balance/ledger consumer that sums customer.payments
    # must exclude is_reversed=True rows.
    is_reversed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-payment_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_customerpayment_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_customerpayment_single_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer}: {self.amount} ({self.payment_date})"


class PaymentAllocation(TimeStampedModel):
    """Imputation of (part of) a CustomerPayment onto one Invoice, or onto
    the customer's general credit balance when invoice is null
    (docs/PHASE_5_PLAN.md Etape 1;
    ERP_Implementation_Experience_Guide.md Section 8.3/1.7).

    "Sum of allocations for a payment must not exceed the payment amount"
    is a cross-row invariant that cannot be a DB CheckConstraint - it is
    enforced by PaymentAllocationService.allocate_payment() under
    select_for_update (Etape 6), not here.
    """

    payment = models.ForeignKey(
        CustomerPayment, on_delete=models.CASCADE, related_name="allocations"
    )
    invoice = models.ForeignKey(
        "sales.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="allocations"
    )
    # Settles a customer's OpeningDebt instead of an invoice (2026-10-11).
    # Never both: a row with neither is unallocated credit.
    opening_debt = models.ForeignKey(
        "finance.OpeningDebt", on_delete=models.PROTECT, null=True, blank=True,
        related_name="allocations",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_paymentallocation_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(invoice__isnull=True) | models.Q(opening_debt__isnull=True),
                name="finance_paymentallocation_single_target",
            ),
        ]

    def __str__(self) -> str:
        if self.opening_debt_id:
            return f"{self.payment_id}: {self.amount} -> dette anterieure {self.opening_debt_id}"
        target = self.invoice.invoice_number if self.invoice_id else "unallocated credit"
        return f"{self.payment_id}: {self.amount} -> {target}"


class SupplierPayment(AuditableModel, TimeStampedModel):
    """Money paid to a supplier, either against a specific SupplierOrder or
    as a general advance (docs/PHASE_5_PLAN.md Etape 2;
    ERP_Implementation_Experience_Guide.md Section 8.5).

    Unlike CustomerPayment there is no indirect-payment case here, so
    exactly one of bank_account/cash_account is required at the DB level
    (not just "never both").
    """

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"
        OTHER = "OTHER", "Other"

    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="payments"
    )
    supplier_order = models.ForeignKey(
        "purchasing.SupplierOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    # Pays a supplier OpeningDebt instead of an order (2026-10-11).
    opening_debt = models.ForeignKey(
        "finance.OpeningDebt", on_delete=models.PROTECT, null=True, blank=True,
        related_name="supplier_payments",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices)
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="supplier_payments"
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="supplier_payments"
    )
    is_advance = models.BooleanField(default=False)
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="supplier_payments_recorded"
    )
    # Set only by SupplierPaymentCancellationService.cancel_supplier_payment
    # (Task 6, client business decision confirmed 2026-09-06) - never a hard
    # delete (AuditableModel.is_locked_for_deletion blocks that once past
    # draft), so every balance/ledger consumer that sums a supplier's/
    # order's payments must exclude is_reversed=True rows. Mirrors
    # CustomerPayment.is_reversed above exactly.
    is_reversed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-payment_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_supplierpayment_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_supplierpayment_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_supplierpayment_requires_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier}: {self.amount} ({self.payment_date})"


class SupplierAdvance(AuditableModel, TimeStampedModel):
    """A cash advance handed to a supplier ahead of any confirmed debt
    (docs/superpowers/specs/2026-08-31-supplier-transporter-advances-design.md).

    Becomes a credit consumed later, oldest-first, by AdvanceConsumption
    rows created automatically when a SupplierOrder is confirmed.
    `remaining_amount` is always derived from those rows, never stored, so
    it can never drift (same "computed, never stored" convention as
    BankAccount.current_balance).
    """

    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="advances"
    )
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="supplier_advances",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="supplier_advances",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supplier_advances",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="supplier_advances_recorded"
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_supplieradvance_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_supplieradvance_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_supplieradvance_requires_account",
            ),
        ]

    def __str__(self) -> str:
        return f"Advance to {self.supplier}: {self.amount} ({self.date})"

    @property
    def remaining_amount(self) -> Decimal:
        consumed = (
            self.consumptions.filter(reversed_at__isnull=True).aggregate(
                total=models.Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        return self.amount - consumed


class TransporterAdvance(AuditableModel, TimeStampedModel):
    """A road-expense advance handed to a transporter ahead of settlement
    (docs/PHASE_5_PLAN.md Etape 3; guide Section 8.6), now a real treasury
    outflow like SupplierAdvance (docs/superpowers/specs/
    2026-08-31-supplier-transporter-advances-design.md) - it previously had
    no bank_account/cash_account and never posted a TreasuryTransaction.

    `settled` is a derived property (remaining_amount <= 0), never a stored
    field - AdvanceConsumptionService is the only writer of the
    AdvanceConsumption rows it's computed from. bank_account/cash_account/
    document/recorded_by are nullable at the DB level only to keep rows
    created before this change valid; every new advance requires them.
    """

    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, related_name="advances"
    )
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="transporter_advances",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="transporter_advances",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transporter_advances",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="transporter_advances_recorded",
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_transporteradvance_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Advance to {self.transporter}: {self.amount} ({self.date})"

    @property
    def remaining_amount(self) -> Decimal:
        consumed = (
            self.consumptions.filter(reversed_at__isnull=True).aggregate(
                total=models.Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        return self.amount - consumed

    @property
    def settled(self) -> bool:
        return self.remaining_amount <= Decimal("0.00")


class AdvanceConsumption(TimeStampedModel):
    """One FIFO allocation of an open SupplierAdvance/TransporterAdvance
    against a real debt (a confirmed SupplierOrder or a TransportPayment) -
    never a mutation of either row, so the ledger stays auditable
    (docs/superpowers/specs/2026-08-31-supplier-transporter-advances-design.md).

    reversed_at marks a consumption undone because the underlying
    SupplierOrder was cancelled after consuming an advance - the row is
    kept (never deleted) so the ledger shows both the consumption and its
    reversal; remaining_amount on the advance always excludes rows with
    reversed_at set.
    """

    supplier_advance = models.ForeignKey(
        SupplierAdvance, on_delete=models.PROTECT, null=True, blank=True,
        related_name="consumptions",
    )
    transporter_advance = models.ForeignKey(
        TransporterAdvance, on_delete=models.PROTECT, null=True, blank=True,
        related_name="consumptions",
    )
    debt_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    debt_object_id = models.PositiveIntegerField()
    debt_object = GenericForeignKey("debt_content_type", "debt_object_id")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_advanceconsumption_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supplier_advance__isnull=True, transporter_advance__isnull=False)
                    | models.Q(supplier_advance__isnull=False, transporter_advance__isnull=True)
                ),
                name="finance_advanceconsumption_single_advance",
            ),
        ]

    def __str__(self) -> str:
        advance = self.supplier_advance or self.transporter_advance
        return f"{advance}: {self.amount} -> {self.debt_object}"


class OpeningDebt(AuditableModel, TimeStampedModel):
    """"Nouvelle dette" (client request 2026-10-11): a debt that existed
    before the company started using the app - what a customer already owed
    the company, or what the company already owed a supplier/transporter.

    Treated like any other debt of that party: it counts in the party's
    balance, is paid by the same flows (customer receipts are distributed to
    it, supplier/transporter "Nouveau paiement" covers it oldest-first) and
    consumes the party's open advances/credit when it is recorded. It never
    moves treasury itself: the money moved before the app existed.

    Exactly one of customer/supplier/transporter is set. Cancelling (only
    while nothing has been paid on it) sets cancelled_at; it is never
    deleted (AuditableModel).
    """

    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_debts",
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_debts",
    )
    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_debts",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="opening_debts",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="opening_debts_recorded"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_openingdebt_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(customer__isnull=False, supplier__isnull=True, transporter__isnull=True)
                    | models.Q(customer__isnull=True, supplier__isnull=False, transporter__isnull=True)
                    | models.Q(customer__isnull=True, supplier__isnull=True, transporter__isnull=False)
                ),
                name="finance_openingdebt_single_party",
            ),
        ]

    def __str__(self) -> str:
        party = self.customer or self.supplier or self.transporter
        return f"Dette anterieure {party}: {self.amount} ({self.date})"


class TransportPayment(AuditableModel, TimeStampedModel):
    """Settlement of a trip's transport cost, net of loss deductions and any
    advance consumed (docs/PHASE_5_PLAN.md Etape 3;
    guide Section 1.5/8.6: earned - deductions - advances - payments =
    transporter outstanding).

    `deduction_amount` is a plain snapshot copied in from the trip's
    TransportDeduction total at settlement time - the deduction rows
    themselves stay the auditable source of truth (guide Section 1.5: "do
    not silently reduce the transport cost field").

    AuditableModel since 2026-09-17 (commission correction feature): a
    settled commission's amount can now be corrected in place
    (TransportPaymentCorrectionService) - this gives that, and /cancel/,
    the same automatic AuditLog trail Expense already has.
    """

    class CalculationMethod(models.TextChoices):
        FIXED = "FIXED", "Fixed"
        PER_LITRE = "PER_LITRE", "Per litre"
        PER_DAY = "PER_DAY", "Per day"
        NEGOTIATED = "NEGOTIATED", "Negotiated"

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        PAYABLE = "PAYABLE", "Payable"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"
        DEDUCTION_APPLIED = "DEDUCTION_APPLIED", "Deduction applied"
        # Bug fix (2026-09-03 recette manuelle): set by
        # TransportPaymentCancellationService.cancel_transport_payment when
        # the underlying Trip is cancelled - never a hard delete, so the
        # payment stays auditable and is excluded from open-debt totals.
        CANCELLED = "CANCELLED", "Cancelled"

    trip = models.ForeignKey(
        "trips.Trip", on_delete=models.PROTECT, related_name="transport_payments"
    )
    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, related_name="transport_payments"
    )
    calculation_method = models.CharField(max_length=20, choices=CalculationMethod.choices)
    base_amount = models.DecimalField(max_digits=16, decimal_places=2)
    unit_price_per_litre = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    deduction_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    advance_applied = models.ForeignKey(
        TransporterAdvance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_payments",
    )
    net_amount = models.DecimalField(max_digits=16, decimal_places=2, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(base_amount__gte=0),
                name="finance_transportpayment_base_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(deduction_amount__gte=0),
                name="finance_transportpayment_deduction_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Transport payment for {self.trip.reference}: {self.net_amount}"

    def save(self, *args, **kwargs):
        # Imported lazily to avoid a circular import at module load time:
        # apps.finance.services imports apps.finance.models at module level.
        from apps.finance.services import AdvanceConsumptionService

        is_new = self._state.adding
        if is_new:
            # Bug fix (recette annexe, 2026-09-06): deduction_amount must
            # not depend on the caller remembering to pass it - the
            # frontend's TransportPaymentForm.vue never sends it, so a
            # payment created after a loss was already discovered (delivery
            # or client verification, whose own sync_transport_shortage_
            # deduction only reaches payments that already exist at that
            # point) would otherwise start at 0 forever, regardless of the
            # order of actions. The trip's TransportDeduction rows are
            # already the single source of truth for this amount (see class
            # docstring) - fall back to their live total whenever the
            # caller left this field at its default. A caller that
            # explicitly supplies a non-zero deduction_amount (existing
            # unit tests exercising the net_amount formula in isolation,
            # with no TransportDeduction row at all) is left untouched.
            if self.deduction_amount == Decimal("0.00"):
                self.deduction_amount = (
                    TransportDeduction.objects.filter(trip_id=self.trip_id)
                    .exclude(status=TransportDeduction.Status.CANCELLED)
                    .aggregate(total=models.Sum("amount"))["total"]
                    or Decimal("0.00")
                )
            self.net_amount = (self.base_amount - self.deduction_amount).quantize(Decimal("0.01"))
            super().save(*args, **kwargs)
            consumed = AdvanceConsumptionService.consume_for_transport_payment(self)
            if consumed > Decimal("0.00"):
                self.net_amount = (
                    self.base_amount - self.deduction_amount - consumed
                ).quantize(Decimal("0.01"))
                super().save(update_fields=["net_amount", "updated_at"])
        else:
            consumed = AdvanceConsumptionService.get_consumed_amount(self)
            self.net_amount = (
                self.base_amount - self.deduction_amount - consumed
            ).quantize(Decimal("0.01"))
            super().save(*args, **kwargs)

    def is_locked_for_deletion(self) -> bool:
        # Same carve-out as Expense.is_locked_for_deletion: a commission
        # with no financial history yet is a genuine draft (can_modify_
        # commission() already gates TransportPaymentViewSet.destroy() the
        # same way) - anything settled/advance-linked stays hard-delete-
        # blocked by AuditableModel's default, unwindable only via /cancel/
        # or /correct/.
        from .commission import can_modify_commission

        return not can_modify_commission(self)


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=30, unique=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name


class Expense(AuditableModel, TimeStampedModel):
    """A company operating cost, optionally split across several trips,
    trucks, customers, suppliers or transporters via ExpenseAllocation
    (docs/PHASE_5_PLAN.md Etape 4; guide Section 8.7).

    `paid_by_customer_directly` flags the indirect-payment case (guide
    Section 1.6/8.9): IndirectSettlementService (Etape 6) is the only path
    that should set this alongside status=PAID and a matching
    CustomerPayment(is_indirect=True) - it is not toggled by the general
    expense CRUD.
    """

    class Category(models.TextChoices):
        CUSTOMS = "customs", "Customs"
        IMPORT_INTENTION = "import_intention", "Import intention"
        TRANSIT = "transit", "Transit"
        ROAD_TRANSIT = "road_transit", "Road transit"
        TRANSPORT = "transport", "Transport"
        LOADING = "loading", "Loading"
        UNLOADING = "unloading", "Unloading"
        ROAD = "road", "Road"
        ADMINISTRATION = "administration", "Administration"
        RENT = "rent", "Rent"
        SALARY = "salary", "Salary"
        REPAIRS = "repairs", "Repairs"
        BANK_CHARGES = "bank_charges", "Bank charges"
        OTHER = "other", "Other"

    class CalculationMethod(models.TextChoices):
        FIXED = "FIXED", "Fixed"
        PER_LITRE = "PER_LITRE", "Per litre"
        PERCENTAGE = "PERCENTAGE", "Percentage"
        PER_ORDER = "PER_ORDER", "Per order"
        PER_TRUCK = "PER_TRUCK", "Per truck"
        MANUAL = "MANUAL", "Manual"

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    # System trip-fee categories (ExpenseCategory.is_system seed, migration
    # 0014) plus the retired "transport" one, which may still tag old trip
    # fees. Every other category - including user-created ones, "unloading"
    # and "import_intention" - is a general expense (Rapport des depenses
    # generales, spec 2026-09-23-rapports-capital-dettes-creances, N4).
    TRIP_FEE_CATEGORY_CODES = frozenset(
        {"customs", "transit", "road_transit", "road", "loading", "transport"}
    )

    category = models.CharField(max_length=30)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    calculation_method = models.CharField(max_length=20, choices=CalculationMethod.choices)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    paid_by_customer_directly = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    # Set only by IndirectSettlementService.record_indirect_payment, so
    # ExpensePostingService.cancel_paid_expense (Phase 5) can find and
    # reverse the exact CustomerPayment an indirect settlement created,
    # without guessing from amount/date. SET_NULL: cancelling deletes the
    # CustomerPayment (the synthetic proxy IndirectSettlementService
    # created purely to restore the receivable), not the Expense.
    indirect_settlement_payment = models.ForeignKey(
        "CustomerPayment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settled_expenses",
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_expense_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_category_display()}: {self.amount} ({self.date})"

    def get_category_display(self) -> str:
        legacy_label = dict(self.Category.choices).get(self.category)
        if legacy_label:
            return legacy_label
        return (
            ExpenseCategory.objects.filter(code=self.category)
            .values_list("name", flat=True)
            .first()
            or self.category
        )

    def is_locked_for_deletion(self) -> bool:
        # Bug fix (2026-09-03 recette manuelle): an UNPAID expense has no
        # accounting impact yet - same "genuine draft state" carve-out as
        # TransportDeduction.is_locked_for_deletion above. Anything past
        # UNPAID (PAID/PARTIALLY_PAID/CANCELLED) stays hard-delete-blocked
        # by AuditableModel's default - only /cancel/ may unwind those.
        return self.status != self.Status.UNPAID


class ExpenseAllocation(TimeStampedModel):
    """Split of one Expense's amount across one or more operational
    entities - a trip, truck, customer, supplier order, etc.
    (docs/PHASE_5_PLAN.md Etape 4; guide Section 8.7: "a customs payment
    may affect several trips").
    """

    expense = models.ForeignKey(
        Expense, on_delete=models.CASCADE, related_name="allocations"
    )
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")
    allocated_amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(allocated_amount__gt=0),
                name="finance_expenseallocation_allocated_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.expense_id}: {self.allocated_amount} -> {self.content_object}"


class TreasuryTransaction(AuditableModel, TimeStampedModel):
    """One movement of company cash/bank money (docs/PHASE_5_PLAN.md Etape 5;
    guide Section 8.10/1.6/D).

    Exactly one of bank_account/cash_account is required - the same
    exclusivity rule as CustomerPayment/SupplierPayment, expressed as a DB
    CheckConstraint here because the plan calls it out explicitly for this
    model. `source_object` traces back to the CustomerPayment/SupplierPayment/
    Expense/etc. that caused this movement, except for the indirect-payment
    case (guide Section 1.6) which never creates a row here at all.

    `type` only ever holds MONEY_IN/MONEY_OUT: current_balance sums this
    field per account (guide Section D: "changes account balances"), and a
    third TRANSFER value would make that direction unrecoverable for the
    two legs TreasuryService.record_transfer() writes. `is_transfer` marks
    those two legs instead (source=MONEY_OUT, destination=MONEY_IN, both
    is_transfer=True) so a future profit/loss report can exclude them
    (guide Section D: "does not create revenue/expense, does not change
    profit") without that flag ever affecting the balance sum itself.
    """

    class Type(models.TextChoices):
        MONEY_IN = "MONEY_IN", "Money in"
        MONEY_OUT = "MONEY_OUT", "Money out"

    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    is_transfer = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)
    source_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    source_object_id = models.PositiveIntegerField(null=True, blank=True)
    source_object = GenericForeignKey("source_content_type", "source_object_id")
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="treasury_transactions"
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="treasury_transactions_recorded"
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_treasurytransaction_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_treasurytransaction_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_treasurytransaction_requires_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type}: {self.amount} ({self.date})"


class Shareholder(TimeStampedModel):
    """A company associate/shareholder (Task 7, client modifications plan).

    Plain master data (like BankAccount/CashAccount) rather than
    AuditableModel: it is a party record, not itself a money movement -
    ShareholderWithdrawal (AuditableModel) is where the auditable financial
    event lives. `participation_percent` is this shareholder's ongoing
    share of company profit; ShareholderProfitShare.percent_snapshot
    freezes it at each distribution so a later edit here never rewrites
    history (see that model's docstring).
    """

    name = models.CharField(max_length=150)
    participation_percent = models.DecimalField(max_digits=5, decimal_places=2)
    contribution = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(participation_percent__gte=0)
                & models.Q(participation_percent__lte=100),
                name="finance_shareholder_percent_range",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active"], name="finance_shareholder_active_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ShareholderProfitPeriod(AuditableModel, TimeStampedModel):
    """A business-controlled profit period with no fixed calendar length.

    Exactly one period may be OPEN. Closing freezes its net profit, creates
    and validates the shareholder distribution atomically and snapshots every
    sold trip (ShareholderProfitPeriodTripSnapshot) - it never blocks later
    writes: anything done afterwards, even on an older trip or debt, counts in
    the open period (client decision 2026-10-05). The latest period may be
    reopened only with an audit reason and only while none of its profit
    shares has been withdrawn.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    net_profit = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    distribution = models.ForeignKey(
        "finance.ShareholderProfitDistribution",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_periods",
    )
    opened_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="profit_periods_opened"
    )
    closed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="profit_periods_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="profit_periods_reopened",
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.TextField(blank=True)
    reopen_count = models.PositiveIntegerField(default=0)
    # Running totals frozen at closure (spec 2026-10-05-periodes-
    # independantes): the open period's figures are "now minus these",
    # so anything done after the closure - even on an older trip or debt -
    # lands in the open period. Null while OPEN.
    general_expenses_paid_snapshot = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    distributed_total_snapshot = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["status"], condition=models.Q(status="OPEN"),
                name="finance_one_open_profit_period",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="OPEN", end_date__isnull=True)
                    | models.Q(status="CLOSED", end_date__isnull=False)
                ),
                name="finance_profit_period_status_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="finance_profit_period_date_order",
            ),
        ]
        indexes = [models.Index(fields=["status", "start_date"], name="finance_profitperiod_state_idx")]

    def __str__(self) -> str:
        return f"Profit period {self.start_date} - {self.end_date or 'open'}"

    def is_locked_for_deletion(self) -> bool:
        # An OPEN period never carries a distribution or a frozen
        # net_profit (only close_period sets those) - it is a pure
        # bookkeeping marker, never financial history. Once CLOSED, even
        # once, it is locked forever like every other AuditableModel.
        # ShareholderProfitPeriodService.reopen_period relies on this to
        # retract an auto-opened successor that was never itself closed.
        return self.status != self.Status.OPEN


class ShareholderProfitPeriodTripSnapshot(models.Model):
    """One sold trip's margin-report row as it stood when `period` closed.

    The open period shows each trip's change since this row (a new trip
    counts in full), so a late fee or client quantity control on an old
    trip appears as an adjustment instead of silently rewriting history.
    `trip` is SET_NULL so a later-deleted trip still shows as a negative
    adjustment from `data`.
    """

    period = models.ForeignKey(
        ShareholderProfitPeriod, on_delete=models.CASCADE, related_name="trip_snapshots"
    )
    trip = models.ForeignKey(
        "trips.Trip", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="profit_snapshots",
    )
    margin = models.DecimalField(max_digits=16, decimal_places=2)
    data = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["period", "trip"], name="finance_profit_snapshot_period_trip"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.period_id}: {self.data.get('trip_reference')} = {self.margin}"


class ShareholderProfitDistribution(AuditableModel, TimeStampedModel):
    """One profit-sharing period: a total company profit figure split
    across active shareholders as of the moment it is created (Task 7,
    client modifications plan).

    AuditableModel (2026-09-08 review, point 9): creation, validation and
    cancellation each write an AuditLog row (CREATE / UPDATE / CANCEL - the
    status->CANCELLED move is inferred as a CANCEL action). The service
    methods pass the acting user explicitly via save(user=actor) so the
    trail is attributed even outside an HTTP request. Never hard-deletable
    (is_locked_for_deletion defaults True) - cancellation is the only way
    to void one.

    Created DRAFT with its ShareholderProfitShare rows already calculated
    (ShareholderDistributionService.create_distribution) so managers can
    review the split before committing to it; `validate` (mirroring
    Invoice's DRAFT -> VALIDATED flow) freezes it by stamping
    validated_by/validated_at.

    Financial effect is gated strictly on status (2026-09-08 review,
    "modele metier definitif"):
    - DRAFT: a preparatory proposal only. Its ShareholderProfitShare rows
      may exist to preview the split, but they credit no available
      balance, reduce no distributable result, and no withdrawal may be
      booked against them.
    - VALIDATED: the split becomes a real engagement of the company. The
      validated shares raise each shareholder's available balance and
      lower the still-distributable result (never any treasury movement -
      that only happens on an actual ShareholderWithdrawal).
    - CANCELLED (added 2026-09-08, reversing "Task 7 ruling 2"): a DRAFT or
      VALIDATED distribution voided by
      ShareholderDistributionService.cancel_distribution, only while no
      ShareholderWithdrawal has ever been recorded against one of its
      shares. It is kept for audit history (its shares are never deleted)
      but grants no further right and can never be validated again.

    Every downstream calculation (ShareholderLedgerService.
    get_available_balance / get_shareholder_summary,
    ShareholderProfitPreviewService.get_preview's already_distributed, the
    dashboard's remaining_to_pay_shareholders) counts VALIDATED shares only, so
    the state of a distribution is reflected everywhere at once.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        CANCELLED = "CANCELLED", "Cancelled"

    period_start = models.DateField()
    period_end = models.DateField()
    total_profit = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="shareholder_distributions_created"
    )
    validated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shareholder_distributions_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shareholder_distributions_cancelled",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period_start", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_profit__gt=0),
                name="finance_shareholderprofitdistribution_total_profit_positive",
            ),
            # 2026-09-08 review, point 6: a DB-level guarantee that two
            # non-cancelled distributions can never cover overlapping
            # periods - the service-level .exists() check is not atomic
            # against two concurrent creates. Partial exclusion constraint
            # (needs btree_gist): CANCELLED rows are exempt so a corrected
            # distribution can reuse a voided one's period.
            ExclusionConstraint(
                name="finance_shrdist_no_overlapping_active_period",
                expressions=[
                    (
                        models.Func(
                            models.F("period_start"),
                            models.F("period_end"),
                            models.Value("[]"),
                            function="daterange",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=models.Q(status__in=["DRAFT", "VALIDATED"]),
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="finance_shrdist_status_idx"),
            models.Index(fields=["period_start", "period_end"], name="finance_shrdist_period_idx"),
        ]

    def __str__(self) -> str:
        return f"Distribution {self.period_start} - {self.period_end}: {self.total_profit}"


class ShareholderProfitShare(TimeStampedModel):
    """One shareholder's calculated slice of a ShareholderProfitDistribution
    (Task 7, client modifications plan).

    `percent_snapshot` is copied from Shareholder.participation_percent at
    distribution-creation time, never read live from Shareholder afterward -
    a later change to a shareholder's ongoing percentage must not
    retroactively alter a historical distribution's amounts.
    `amount_withdrawn` is a stored cache, but the only writer is
    `sync_amount_withdrawn()`, which always recomputes it as
    Sum(withdrawals.amount) - it can never silently drift from the actual
    ShareholderWithdrawal rows because it is never incremented ad hoc.
    """

    distribution = models.ForeignKey(
        ShareholderProfitDistribution, on_delete=models.CASCADE, related_name="shares"
    )
    shareholder = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, related_name="profit_shares"
    )
    percent_snapshot = models.DecimalField(max_digits=5, decimal_places=2)
    amount_due = models.DecimalField(max_digits=16, decimal_places=2, editable=False)
    amount_withdrawn = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, editable=False
    )

    class Meta:
        ordering = ["-distribution_id", "shareholder_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(percent_snapshot__gte=0) & models.Q(percent_snapshot__lte=100),
                name="finance_shareholderprofitshare_percent_range",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_due__gte=0),
                name="finance_shareholderprofitshare_amount_due_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_withdrawn__gte=0),
                name="finance_shareholderprofitshare_amount_withdrawn_non_negative",
            ),
            models.UniqueConstraint(
                fields=["distribution", "shareholder"],
                name="finance_shareholderprofitshare_one_per_shareholder",
            ),
        ]
        indexes = [
            models.Index(fields=["shareholder"], name="finance_shrshare_shr_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.shareholder}: {self.amount_due} ({self.distribution_id})"

    @property
    def remaining_due(self) -> Decimal:
        return self.amount_due - self.amount_withdrawn

    def sync_amount_withdrawn(self) -> Decimal:
        """Recompute amount_withdrawn from the actual
        ShareholderWithdrawalAllocation rows against this share - the only
        way this field is ever written, so it can never drift from
        withdrawal history (Task 7, client modifications plan: "avoid a
        field that can silently drift")."""
        # A company advance deducted from this share consumes it exactly
        # like a withdrawal (client request 2026-10-11).
        total = (
            self.withdrawal_allocations.aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        ) + (
            self.advance_deductions.aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.amount_withdrawn = total
        self.save(update_fields=["amount_withdrawn", "updated_at"])
        return total


class ShareholderLoan(TimeStampedModel):
    """An advance taken by an associate (the borrower), from one of two
    sources (client request 2026-10-11):

    - SHAREHOLDER: another associate (the lender) advances part of his
      own balance (client correction 2026-10-11): the lender's balance
      goes down and the borrower's goes up by the amount - the borrower
      can withdraw it - while the debt/claim is tracked here. A repayment
      moves the money back from the borrower's balance to the lender's.
      Recording it never touches treasury; only a withdrawal does.
    - COMPANY: the company grants him an advance on his future profit.
      Like a profit distribution it moves no treasury when recorded: it is
      shown in his grand livre and becomes withdrawable - money only
      leaves treasury when he actually withdraws it (a
      ShareholderWithdrawal allocated against this advance, tracked by
      `amount_drawn`). It is a debt of the borrower to the company,
      deducted automatically from his next VALIDATED profit share
      (ShareholderLoanService.apply_advances_to_distribution) or repaid
      into a treasury account.

    Every repayment is a ShareholderLoanRepayment row; `amount_repaid` is
    their running total, only ever moved under this row's lock.

    `status` is derived in save() from amount_repaid vs amount (same
    "computed on save" convention as TransportPayment.net_amount) rather
    than set directly by the client, so it can never disagree with the two
    numbers it summarizes.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PARTIALLY_REPAID = "PARTIALLY_REPAID", "Partially repaid"
        REPAID = "REPAID", "Repaid"

    class Source(models.TextChoices):
        SHAREHOLDER = "SHAREHOLDER", "Shareholder"
        COMPANY = "COMPANY", "Company"

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.SHAREHOLDER)
    borrower = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, related_name="loans_borrowed"
    )
    lender = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, null=True, blank=True, related_name="loans_lent"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    amount_repaid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    # How much of the advance the borrower has actually withdrawn
    # (recomputed from ShareholderWithdrawalAllocation rows only).
    amount_drawn = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, editable=False
    )
    # COMPANY only: part given back before ever being withdrawn - a
    # cancellation of the credit, which never touches treasury.
    amount_cancelled = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, editable=False
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_loans_recorded",
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shareholderloan_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_repaid__gte=0),
                name="finance_shareholderloan_amount_repaid_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_repaid__lte=models.F("amount")),
                name="finance_shareholderloan_repaid_not_exceeding_amount",
            ),
            models.CheckConstraint(
                condition=~models.Q(borrower=models.F("lender")),
                name="finance_shareholderloan_borrower_not_lender",
            ),
            # An associate advance has a lender; a company advance has none.
            models.CheckConstraint(
                condition=(
                    models.Q(source="SHAREHOLDER", lender__isnull=False)
                    | models.Q(source="COMPANY", lender__isnull=True)
                ),
                name="finance_shareholderloan_source_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_drawn__gte=0)
                & models.Q(amount_drawn__lte=models.F("amount")),
                name="finance_shareholderloan_drawn_within_amount",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_cancelled__gte=0)
                & models.Q(amount_cancelled__lte=models.F("amount") - models.F("amount_drawn")),
                name="finance_shareholderloan_cancelled_within_undrawn",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="finance_shrloan_status_idx"),
            models.Index(fields=["date"], name="finance_shrloan_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.lender or 'Entreprise'} -> {self.borrower}: {self.amount}"

    @property
    def remaining_amount(self) -> Decimal:
        return self.amount - self.amount_repaid

    @property
    def undrawn_amount(self) -> Decimal:
        """Part of the advance the borrower can still withdraw. A company
        advance stays withdrawable until drawn (its debt is separate); an
        associate advance stops being withdrawable once given back."""
        if self.source == self.Source.COMPANY:
            return self.amount - self.amount_drawn - self.amount_cancelled
        return max(Decimal("0.00"), self.amount - self.amount_drawn - self.amount_repaid)

    @property
    def cash_outstanding(self) -> Decimal:
        """COMPANY only: money that really left treasury for this advance
        and has not come back yet (neither repaid in cash nor deducted from
        a profit share) - the most a treasury repayment may bring back."""
        if self.source != self.Source.COMPANY:
            return Decimal("0.00")
        return max(Decimal("0.00"), self.remaining_amount - self.undrawn_amount)

    @property
    def borrower_balance_effect(self) -> Decimal:
        """What an associate advance adds to the borrower's balance: what
        he received, minus what he withdrew from it and what he gave back
        (negative once he repays more than he still holds of it)."""
        return self.amount - self.amount_drawn - self.amount_repaid

    def sync_amount_drawn(self) -> Decimal:
        total = (
            self.withdrawal_allocations.aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.amount_drawn = total
        self.save(update_fields=["amount_drawn", "updated_at"])
        return total

    def save(self, *args, **kwargs):
        if self.amount_repaid <= 0:
            self.status = self.Status.OPEN
        elif self.amount_repaid < self.amount:
            self.status = self.Status.PARTIALLY_REPAID
        else:
            self.status = self.Status.REPAID
        super().save(*args, **kwargs)


class ShareholderLoanRepayment(TimeStampedModel):
    """One repayment of a ShareholderLoan (client request 2026-10-11):

    - DIRECT: an associate advance repaid by the borrower to the lender,
      outside company treasury.
    - TREASURY: a company advance repaid into a bank/cash account (one
      TreasuryTransaction MONEY_IN).
    - CANCEL: the part of a company advance given back before it was ever
      withdrawn - the credit is cancelled, no money moves (client
      correction 2026-10-11: treasury only moves for real money).
    - PROFIT_SHARE: a company advance deducted automatically from the
      borrower's VALIDATED profit share - that share is consumed by the
      deduction (ShareholderProfitShare.sync_amount_withdrawn counts it),
      since the money already left treasury when the advance was paid.
      Removed again if that distribution is cancelled.
    """

    class Method(models.TextChoices):
        DIRECT = "DIRECT", "Direct"
        TREASURY = "TREASURY", "Treasury"
        PROFIT_SHARE = "PROFIT_SHARE", "Profit share"
        CANCEL = "CANCEL", "Cancelled (never withdrawn)"

    loan = models.ForeignKey(ShareholderLoan, on_delete=models.CASCADE, related_name="repayments")
    method = models.CharField(max_length=20, choices=Method.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_advance_repayments",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_advance_repayments",
    )
    profit_share = models.ForeignKey(
        ShareholderProfitShare, on_delete=models.PROTECT, null=True, blank=True,
        related_name="advance_deductions",
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_loan_repayments_recorded",
    )

    class Meta:
        ordering = ["date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shrloanrepayment_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(method__in=["DIRECT", "CANCEL"], profit_share__isnull=True,
                             bank_account__isnull=True, cash_account__isnull=True)
                    | models.Q(method="PROFIT_SHARE", profit_share__isnull=False,
                               bank_account__isnull=True, cash_account__isnull=True)
                    | models.Q(method="TREASURY", profit_share__isnull=True,
                               bank_account__isnull=False, cash_account__isnull=True)
                    | models.Q(method="TREASURY", profit_share__isnull=True,
                               bank_account__isnull=True, cash_account__isnull=False)
                ),
                name="finance_shrloanrepayment_method_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"LOAN-{self.loan_id}: {self.amount} ({self.method})"


class ShareholderWithdrawal(AuditableModel, TimeStampedModel):
    """Money paid out from company treasury to a shareholder (Task 7,
    client modifications plan). Which profit share(s) and/or capital
    contribution(s) it actually drew from is recorded on its `allocations`
    (ShareholderWithdrawalAllocation, design doc
    2026-09-15-capital-associe-retrait-design.md) - always at least one,
    computed automatically by ShareholderWithdrawalService.record_withdrawal
    (profit due first, oldest first; the shareholder's own capital next,
    oldest first).

    AuditableModel + the same bank_account/cash_account exclusivity
    constraint as SupplierPayment, since this is a real money-out event
    that must post to treasury exactly like a supplier payment does
    (ShareholderWithdrawalService.record_withdrawal /
    FinancePostingService.record_shareholder_withdrawal_treasury).
    """

    shareholder = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, related_name="withdrawals"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="shareholder_withdrawals"
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="shareholder_withdrawals"
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="shareholder_withdrawals_recorded"
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shareholderwithdrawal_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_shareholderwithdrawal_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_shareholderwithdrawal_requires_account",
            ),
        ]
        indexes = [
            models.Index(fields=["shareholder", "date"], name="finance_shrwd_shr_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.shareholder}: {self.amount} ({self.date})"


class ShareholderContribution(AuditableModel, TimeStampedModel):
    """Real cash injected into the company by a shareholder/associate
    (Phase 1, docs/superpowers/specs/2026-09-02-business-corrections-6-phases-design.md).

    Its still-unreturned amount (`remaining_capital`) DOES contribute to
    `ShareholderLedgerService.get_available_balance()` (design doc
    2026-09-15-capital-associe-retrait-design.md): once a shareholder's
    profit share is exhausted, a withdrawal may draw down their own
    capital, oldest contribution first, tracked one
    ShareholderWithdrawalAllocation row at a time so it never drifts and
    never touches another shareholder's capital.

    The proof document is mandatory here (a capital injection is a
    notable, real money-in event), so creation goes through
    ShareholderContributionService.record_contribution, copied from
    AdvanceService.create_supplier_advance rather than routed through
    FinancePostingService (which only fits flows where the document stays
    optional).
    """

    shareholder = models.ForeignKey(
        Shareholder, on_delete=models.PROTECT, related_name="contributions"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_contributions",
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, null=True, blank=True,
        related_name="shareholder_contributions",
    )
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="shareholder_contributions",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="shareholder_contributions_recorded"
    )
    amount_returned = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, editable=False
    )
    # Admin-only cancellation (2026-10-15): the row is kept, an offsetting
    # MONEY_OUT is posted, and every capital total ignores it.
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        editable=False, related_name="shareholder_contributions_cancelled",
    )
    cancel_reason = models.TextField(blank=True, editable=False)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shareholdercontribution_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=True) | models.Q(cash_account__isnull=True),
                name="finance_shareholdercontribution_single_account",
            ),
            models.CheckConstraint(
                condition=models.Q(bank_account__isnull=False) | models.Q(cash_account__isnull=False),
                name="finance_shareholdercontribution_requires_account",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_returned__gte=0),
                name="finance_shareholdercontribution_amount_returned_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_returned__lte=models.F("amount")),
                name="finance_shareholdercontribution_returned_not_exceeding_amount",
            ),
        ]
        indexes = [
            models.Index(fields=["shareholder", "date"], name="finance_shrcontrib_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.shareholder}: {self.amount} ({self.date})"

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None

    @property
    def remaining_capital(self) -> Decimal:
        if self.is_cancelled:
            return Decimal("0.00")
        return self.amount - self.amount_returned

    def sync_amount_returned(self) -> Decimal:
        """Recompute amount_returned from the actual
        ShareholderWithdrawalAllocation rows against this contribution -
        the only writer, so it can never silently drift (same pattern as
        ShareholderProfitShare.sync_amount_withdrawn)."""
        total = (
            self.withdrawal_allocations.aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.amount_returned = total
        self.save(update_fields=["amount_returned", "updated_at"])
        return total


class ShareholderWithdrawalAllocation(TimeStampedModel):
    """Which pool a withdrawal actually drew from - a profit share or a
    capital contribution, never both on the same row (design doc
    2026-09-15-capital-associe-retrait-design.md). One ShareholderWithdrawal
    (one treasury posting) can have several of these, e.g. a withdrawal
    that exhausts two profit shares and dips into one capital contribution
    produces three rows here. `ShareholderProfitShare.amount_withdrawn` and
    `ShareholderContribution.amount_returned` are both recomputed only from
    these rows (sync_amount_withdrawn/sync_amount_returned), so neither can
    drift from the actual allocation history.
    """

    withdrawal = models.ForeignKey(
        ShareholderWithdrawal, on_delete=models.CASCADE, related_name="allocations"
    )
    profit_share = models.ForeignKey(
        ShareholderProfitShare,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="withdrawal_allocations",
    )
    contribution = models.ForeignKey(
        ShareholderContribution,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="withdrawal_allocations",
    )
    # A company advance being withdrawn (client request 2026-10-11).
    advance = models.ForeignKey(
        ShareholderLoan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="withdrawal_allocations",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_shrwithdrawalalloc_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(profit_share__isnull=False, contribution__isnull=True,
                             advance__isnull=True)
                    | models.Q(profit_share__isnull=True, contribution__isnull=False,
                               advance__isnull=True)
                    | models.Q(profit_share__isnull=True, contribution__isnull=True,
                               advance__isnull=False)
                ),
                name="finance_shrwithdrawalalloc_exactly_one_source",
            ),
        ]
        indexes = [
            models.Index(fields=["withdrawal"], name="finance_shrwdalloc_wd_idx"),
        ]

    def __str__(self) -> str:
        if self.profit_share_id:
            source = f"share {self.profit_share_id}"
        elif self.contribution_id:
            source = f"contribution {self.contribution_id}"
        else:
            source = f"advance {self.advance_id}"
        return f"WD-{self.withdrawal_id}: {self.amount} from {source}"
