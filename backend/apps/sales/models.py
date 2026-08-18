from django.db import models

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
