from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel

CURRENCY_CHOICES = [("XOF", "XOF")]


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


class TransportDeduction(TimeStampedModel):
    """Deduction on a transporter's account for chargeable (out-of-tolerance)
    loss on a trip (docs/PHASE_4_PLAN.md Etape 3;
    ERP_Implementation_Experience_Guide.md Section 7.5).

    A separate transaction row rather than a mutation of the trip's
    transport cost, so the transporter ledger keeps a full audit trail:
    "transport earned - deductions - advances - payments = outstanding"
    (guide Section 7.5) never collapses into a single opaque number.
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

    def save(self, *args, **kwargs):
        self.amount = (self.chargeable_quantity * self.unit_price).quantize(
            Decimal("0.01")
        )
        super().save(*args, **kwargs)


class CustomerPayment(TimeStampedModel):
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
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="customer_payments_recorded"
    )

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
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_paymentallocation_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        target = self.invoice.invoice_number if self.invoice_id else "unallocated credit"
        return f"{self.payment_id}: {self.amount} -> {target}"


class SupplierPayment(TimeStampedModel):
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


class TransporterAdvance(TimeStampedModel):
    """A road-expense advance handed to a transporter ahead of settlement
    (docs/PHASE_5_PLAN.md Etape 3; guide Section 8.6).

    `settled` flips to True once a TransportPayment consumes it -
    TransportPayment.advance_applied is the only writer of that flag.
    """

    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, related_name="advances"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    settled = models.BooleanField(default=False)

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


class TransportPayment(TimeStampedModel):
    """Settlement of a trip's transport cost, net of loss deductions and any
    advance consumed (docs/PHASE_5_PLAN.md Etape 3;
    guide Section 1.5/8.6: earned - deductions - advances - payments =
    transporter outstanding).

    `deduction_amount` is a plain snapshot copied in from the trip's
    TransportDeduction total at settlement time - the deduction rows
    themselves stay the auditable source of truth (guide Section 1.5: "do
    not silently reduce the transport cost field").
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

    trip = models.ForeignKey(
        "trips.Trip", on_delete=models.PROTECT, related_name="transport_payments"
    )
    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, related_name="transport_payments"
    )
    calculation_method = models.CharField(max_length=20, choices=CalculationMethod.choices)
    base_amount = models.DecimalField(max_digits=16, decimal_places=2)
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
        advance_amount = self.advance_applied.amount if self.advance_applied_id else Decimal("0.00")
        self.net_amount = (
            self.base_amount - self.deduction_amount - advance_amount
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
        if self.advance_applied_id and not self.advance_applied.settled:
            TransporterAdvance.objects.filter(pk=self.advance_applied_id).update(settled=True)


class Expense(TimeStampedModel):
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

    category = models.CharField(max_length=30, choices=Category.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    calculation_method = models.CharField(max_length=20, choices=CalculationMethod.choices)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    paid_by_customer_directly = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

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


class TreasuryTransaction(TimeStampedModel):
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
