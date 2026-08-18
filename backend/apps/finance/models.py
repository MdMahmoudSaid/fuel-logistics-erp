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
