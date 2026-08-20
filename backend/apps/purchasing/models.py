from decimal import Decimal

from django.db import models
from django.contrib.contenttypes.fields import GenericRelation

from apps.audit.mixins import AuditableModel
from apps.core.models import TimeStampedModel


class SupplierOrder(AuditableModel, TimeStampedModel):
    """A fuel purchase from a supplier (spec §5).

    `total_amount` is recalculated on every save() for query/list performance,
    but the authoritative reliquat calculation (purchased - active cessions)
    lives in SupplierStockService, not here (see docs/PHASE_2_PLAN.md).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    reference = models.CharField(max_length=100, unique=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="orders"
    )
    product = models.ForeignKey(
        "core.Product", on_delete=models.PROTECT, related_name="supplier_orders"
    )
    purchase_date = models.DateField()
    quantity_litres = models.DecimalField(max_digits=14, decimal_places=2)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    currency = models.CharField(max_length=10, default="XOF")
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, editable=False)
    optional_costs = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="supplier_orders"
    )
    documents = GenericRelation("documents.Document")

    class Meta:
        ordering = ["-purchase_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_litres__gt=0),
                name="purchasing_supplierorder_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="purchasing_supplierorder_unit_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.reference

    def is_locked_for_deletion(self) -> bool:
        return self.status != self.Status.DRAFT

    def save(self, *args, **kwargs):
        total = (self.quantity_litres * self.unit_price) + (
            self.optional_costs or Decimal("0.00")
        )
        self.total_amount = total.quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class CessionLetter(TimeStampedModel):
    """Authorizes loading against a SupplierOrder, up to authorized_quantity.

    `remaining_quantity` is intentionally NOT stored here (see spec §6-7 and
    ERP_Implementation_Experience_Guide.md §5.3) — it is derived data, owned
    by SupplierStockService once Phase 3 loadings exist.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        EXHAUSTED = "EXHAUSTED", "Exhausted"
        CANCELLED = "CANCELLED", "Cancelled"

    reference = models.CharField(max_length=100, unique=True)
    supplier_order = models.ForeignKey(
        SupplierOrder, on_delete=models.PROTECT, related_name="cessions"
    )
    authorized_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    issue_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="cession_letters"
    )
    documents = GenericRelation("documents.Document")

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(authorized_quantity__gt=0),
                name="purchasing_cessionletter_authorized_quantity_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.reference
