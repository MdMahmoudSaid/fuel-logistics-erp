from decimal import Decimal

from django.db import models

from apps.core.models import TimeStampedModel

CURRENCY_CHOICES = [("XOF", "XOF")]


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
        # opening_balance + Σ(TreasuryTransaction) once that model exists
        # (Phase 5, roadmap/phase_5_finance.md) — computed, never stored,
        # so it can never drift from the transaction ledger.
        return self.opening_balance


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
        return self.opening_balance


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
