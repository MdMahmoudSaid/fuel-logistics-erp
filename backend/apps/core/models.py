from decimal import Decimal

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base adding created/updated timestamps to every domain model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Product(TimeStampedModel):
    """Fuel product (Gasoil, Essence, ...). See spec §5."""

    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LossToleranceConfig(TimeStampedModel):
    """Configurable default loss tolerance applied during delivery quantity
    control (docs/PHASE_4_PLAN.md Etape 1;
    ERP_Implementation_Experience_Guide.md Section 7.4: "Do not hard-code
    100 L in services").

    Singleton row, enforced at the application level: save() always forces
    pk=1, so every create/update collapses onto the same row instead of
    accumulating history here. DeliveryControl.tolerance_quantity is what
    freezes the value actually applied to a given trip (guide Section 7.2) -
    this table only ever holds "the current default".
    """

    DEFAULT_TOLERANCE = Decimal("100.00")

    tolerance_litres = models.DecimalField(
        max_digits=10, decimal_places=2, default=DEFAULT_TOLERANCE
    )
    updated_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="tolerance_config_updates"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tolerance_litres__gte=0),
                name="core_losstoleranceconfig_tolerance_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Loss tolerance: {self.tolerance_litres} L"

    def save(self, *args, **kwargs):
        self.pk = 1
        if self.created_at is None:
            # A freshly-constructed instance never has created_at set. Left
            # alone, Django's pk-forced update-then-insert save() would try
            # to UPDATE the existing singleton row's created_at to NULL,
            # violating the not-null constraint - carry the original row's
            # value forward instead so repeated save() calls behave as an
            # upsert rather than erroring on the second one.
            existing_created_at = (
                LossToleranceConfig.objects.filter(pk=1)
                .values_list("created_at", flat=True)
                .first()
            )
            if existing_created_at is not None:
                self.created_at = existing_created_at
        # Always let Django's default "UPDATE, then INSERT if none matched"
        # dance decide insert vs. update - Manager.create() otherwise passes
        # force_insert=True, which would try (and fail) to insert a second
        # row 1 instead of updating the existing singleton.
        kwargs["force_insert"] = False
        kwargs["force_update"] = False
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("LossToleranceConfig is a singleton and cannot be deleted.")

    @classmethod
    def get_current_tolerance(cls) -> Decimal:
        """The tolerance to apply to a delivery confirmed right now.

        Falls back to DEFAULT_TOLERANCE when no admin has ever saved a
        config row yet, so DeliveryService never has to special-case "not
        configured" (spec still requires a 100 L default out of the box).
        """
        config = cls.objects.first()
        return config.tolerance_litres if config else cls.DEFAULT_TOLERANCE


class CompanyProfile(TimeStampedModel):
    """Company details printed on the commercial documents (proforma,
    delivery note, loading sheet, purchase order - spec 2026-10-11
    documents-commerciaux §2). Singleton (pk=1), like LossToleranceConfig."""

    name = models.CharField(max_length=150, blank=True)
    tagline = models.CharField(max_length=150, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    trade_register = models.CharField(max_length=80, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.CharField(max_length=150, blank=True)
    website = models.CharField(max_length=150, blank=True)
    # Profit made before the app was used (the previous application's result,
    # client request 2026-10-17). It counts in the all-time net profit, hence in
    # "Benefice net apres depenses generales" and in what the next period
    # closure distributes. Not exposed by the API/UI: set once with the
    # `set_brought_forward_profit` command. No treasury movement: the money is
    # already in the accounts' opening balances.
    brought_forward_profit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "CompanyProfile":
        return cls.objects.get_or_create(pk=1)[0]

    def pdf_company(self) -> dict:
        """The `company` block of a document PDF; empty lines are dropped and
        the name falls back to the app's default."""
        from apps.reports.services.pdf_template import DEFAULT_COMPANY_NAME

        def join(*parts):
            return " · ".join(p for p in parts if p)

        lines = [
            join(self.address, self.city),
            join(self.phone and f"Tél. : {self.phone}", self.email, self.website),
            join(self.tax_id and f"NIF : {self.tax_id}", self.trade_register and f"RC : {self.trade_register}"),
        ]
        return {
            "name": self.name or DEFAULT_COMPANY_NAME,
            "tagline": self.tagline,
            "lines": [line for line in lines if line],
            "banks": [
                {"bank": b.bank, "swift": b.swift, "account": b.account_number}
                for b in self.bank_accounts.filter(is_active=True)
            ],
        }


class CompanyBankAccount(models.Model):
    """A bank account printed on the documents - informational only, not
    linked to the treasury BankAccount."""

    profile = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name="bank_accounts")
    bank = models.CharField(max_length=100)
    swift = models.CharField(max_length=30, blank=True)
    account_number = models.CharField(max_length=80)
    position = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]
