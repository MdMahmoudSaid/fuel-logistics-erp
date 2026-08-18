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
