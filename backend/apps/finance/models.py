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
