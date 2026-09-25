from decimal import Decimal

from django.db import models

from apps.audit.mixins import AuditableModel
from apps.core.models import TimeStampedModel


class CustomerOrder(TimeStampedModel):
    """Commercial demand envelope, fulfilled by one or more independent
    Trips (docs/PHASE_3_PLAN.md Etape 2;
    ERP_Implementation_Experience_Guide.md §1.1/§6.4).

    Truck != Trip != CustomerOrder: never add a truck/trip foreign key here.
    A customer order is honoured by Trip rows that point back at it
    (`Trip.customer_order`, related_name="trips") — the same physical truck
    may create several of those trips for the same order.

    Aggregated quantities (assigned/loaded/delivered/remaining) and
    trip-driven status recomputation live in
    apps.sales.services.CustomerOrderService, not here, so the formulas are
    never duplicated across serializers/views (guide §5.5).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PARTIALLY_ASSIGNED = "PARTIALLY_ASSIGNED", "Partially assigned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED", "Partially delivered"
        DELIVERED = "DELIVERED", "Delivered"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="orders"
    )
    product = models.ForeignKey(
        "core.Product", on_delete=models.PROTECT, related_name="customer_orders"
    )
    quantity_ordered = models.DecimalField(max_digits=14, decimal_places=2)
    expected_price = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    status = models.CharField(
        max_length=25, choices=Status.choices, default=Status.DRAFT
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_ordered__gt=0),
                name="sales_customerorder_quantity_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Order #{self.pk} - {self.customer} ({self.quantity_ordered} L)"


class Sale(AuditableModel, TimeStampedModel):
    """One commercial sale line, created once a Trip's delivery is confirmed
    (docs/PHASE_4_PLAN.md Etape 4;
    ERP_Implementation_Experience_Guide.md Section 7.6).

    delivered_quantity is written at delivery, then mutable ONLY through
    InvoiceService - adjust_delivered_quantity() (driven by the client
    verification) or correct_invoice(field="delivered_quantity") (a manual
    audited correction). editable=False still guards the Django admin /
    ModelForm paths. It MAY legitimately differ from
    DeliveryControl.received_quantity after a manual correction
    (spec 2026-09-07 §"Cohérence").

    No customer_order FK: the order (if any) is already reachable via
    trip.customer_order, so duplicating it here would be exactly the kind of
    redundant relation guide Section 1.1 warns against.
    """

    trip = models.OneToOneField(
        "trips.Trip", on_delete=models.PROTECT, related_name="sale"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="sales"
    )
    product = models.ForeignKey(
        "core.Product", on_delete=models.PROTECT, related_name="sales"
    )
    # Multi-trip invoice: a Sale normally owns its own Invoice (`invoice`, the
    # OneToOne from Invoice.sale); when several trips of the same customer
    # are grouped on one invoice, the first Sale owns it and the others
    # point at it here.
    grouped_invoice = models.ForeignKey(
        "sales.Invoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="extra_sales",
    )
    delivered_quantity = models.DecimalField(
        max_digits=14, decimal_places=2, editable=False
    )
    unit_selling_price = models.DecimalField(max_digits=14, decimal_places=4)
    currency = models.CharField(max_length=10, default="XOF")
    subtotal = models.DecimalField(max_digits=16, decimal_places=2, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(delivered_quantity__gt=0),
                name="sales_sale_delivered_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_selling_price__gte=0),
                name="sales_sale_unit_selling_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Sale for {self.trip.reference} ({self.delivered_quantity} L)"

    @property
    def billing_invoice(self):
        """The invoice this sale is billed on (its own, or the group's)."""
        return getattr(self, "invoice", None) or self.grouped_invoice

    def save(self, *args, **kwargs):
        self.subtotal = (self.delivered_quantity * self.unit_selling_price).quantize(
            Decimal("0.01")
        )
        super().save(*args, **kwargs)


class ProductSellingPriceHistory(TimeStampedModel):
    """Append-only log of every selling price applied or set, so the last
    price charged per product (and per customer, when set) can always be
    suggested for the next sale without ever overwriting past sales' prices
    (docs/PHASE_4_PLAN.md Etape 4; guide Section 7.8).

    customer=None means a global/default price for the product, checked as
    a fallback when no customer-specific entry exists yet.
    """

    product = models.ForeignKey(
        "core.Product", on_delete=models.CASCADE, related_name="selling_price_history"
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="selling_price_history",
    )
    price = models.DecimalField(max_digits=14, decimal_places=4)
    currency = models.CharField(max_length=10, default="XOF")
    effective_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="price_changes"
    )

    class Meta:
        ordering = ["-effective_at", "-id"]
        verbose_name_plural = "Product selling price histories"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="sales_productsellingpricehistory_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        scope = self.customer or "global"
        return f"{self.product} / {scope}: {self.price}"


class Invoice(AuditableModel, TimeStampedModel):
    """Customer invoice for one Sale (docs/PHASE_4_PLAN.md Etape 4;
    ERP_Implementation_Experience_Guide.md Section 7.9/Section 21).

    Once status=VALIDATED, financial fields (via Sale) must never be
    mutated directly again - InvoiceService.correct_invoice() is the only
    sanctioned path past that point, and it always writes an
    InvoiceCorrection row.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VALIDATED = "VALIDATED", "Validated"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    invoice_number = models.CharField(max_length=50, unique=True)
    sale = models.OneToOneField(
        Sale, on_delete=models.PROTECT, related_name="invoice"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    total_amount = models.DecimalField(max_digits=16, decimal_places=2)
    issued_date = models.DateField()

    class Meta:
        ordering = ["-issued_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="sales_invoice_total_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.invoice_number

    def is_locked_for_deletion(self) -> bool:
        return self.status != self.Status.DRAFT

    @property
    def all_sales(self) -> list:
        """Every Sale billed on this invoice: the primary one first, then
        the trips grouped onto it."""
        return [self.sale, *self.extra_sales.select_related("trip").order_by("id")]

    def recompute_total(self) -> None:
        self.total_amount = sum((s.subtotal for s in self.all_sales), Decimal("0.00"))
        self.save(update_fields=["total_amount", "updated_at"])


class InvoiceCorrection(TimeStampedModel):
    """Append-only audit trail entry for a post-validation invoice
    adjustment (docs/PHASE_4_PLAN.md Etape 4/Etape 5;
    ERP_Implementation_Experience_Guide.md Section 21: "record
    correction/reversal with reason and actor" rather than silently
    rewriting a validated invoice's data).
    """

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="corrections"
    )
    field_name = models.CharField(max_length=50)
    previous_value = models.CharField(max_length=100)
    new_value = models.CharField(max_length=100)
    corrected_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="invoice_corrections"
    )
    corrected_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    class Meta:
        ordering = ["-corrected_at", "-id"]

    def __str__(self) -> str:
        return f"{self.invoice.invoice_number}: {self.field_name} -> {self.new_value}"
