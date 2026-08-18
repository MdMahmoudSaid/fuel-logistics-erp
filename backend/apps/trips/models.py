from django.db import models

from apps.core.models import TimeStampedModel


class Trip(TimeStampedModel):
    """One physical truck movement/load (docs/PHASE_3_PLAN.md Etape 3).

    Merges the "Loading" event into Trip per
    ERP_Implementation_Experience_Guide.md Section 6.6: they share one
    lifecycle at creation time in this project (quantity loaded, cession
    letter, BL, loading date), so a separate 1:1 Loading table would be a
    superfluous join (spec Section 12/42).

    Truck != Trip != CustomerOrder (guide Section 1.1): this is the only
    place a movement's quantity/status/customer information lives - never
    add trip-specific fields back onto Truck, and never make CustomerOrder
    point at a truck directly.
    """

    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        SENT_FOR_LOADING = "SENT_FOR_LOADING", "Sent for loading"
        LOADING = "LOADING", "Loading"
        LOADED = "LOADED", "Loaded"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        BORDER = "BORDER", "Border"
        CUSTOMS = "CUSTOMS", "Customs"
        GOING_TO_CLIENT = "GOING_TO_CLIENT", "Going to client"
        ARRIVED_AT_CLIENT = "ARRIVED_AT_CLIENT", "Arrived at client"
        QUANTITY_CONTROL = "QUANTITY_CONTROL", "Quantity control"
        DELIVERED = "DELIVERED", "Delivered"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
        CANCELLED = "CANCELLED", "Cancelled"

    # A trip in either of these statuses is finished for good: it no longer
    # occupies its truck and no longer counts as "active" for locking
    # purposes (plan Section 1.D / TruckAvailabilityService).
    TERMINAL_STATUSES = {Status.COMPLETED, Status.CANCELLED}

    reference = models.CharField(max_length=50, unique=True)
    truck = models.ForeignKey(
        "transport.Truck", on_delete=models.PROTECT, related_name="trips"
    )
    transporter = models.ForeignKey(
        "transport.Transporter", on_delete=models.PROTECT, related_name="trips"
    )
    driver = models.ForeignKey(
        "transport.Driver",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="trips",
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="trips"
    )
    supplier_order = models.ForeignKey(
        "purchasing.SupplierOrder", on_delete=models.PROTECT, related_name="trips"
    )
    cession_letter = models.ForeignKey(
        "purchasing.CessionLetter", on_delete=models.PROTECT, related_name="trips"
    )
    product = models.ForeignKey(
        "core.Product", on_delete=models.PROTECT, related_name="trips"
    )
    quantity_loaded = models.DecimalField(max_digits=14, decimal_places=2)
    client = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="direct_trips",
    )
    customer_order = models.ForeignKey(
        "sales.CustomerOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="trips",
    )
    loading_date = models.DateField()
    bl_reference = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ASSIGNED
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="trips_created"
    )

    class Meta:
        ordering = ["-loading_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_loaded__gt=0),
                name="trips_trip_quantity_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.reference

    def is_active(self) -> bool:
        return self.status not in self.TERMINAL_STATUSES


class TripStatusHistory(models.Model):
    """Append-only status audit trail (docs/PHASE_3_PLAN.md Etape 3;
    guide Section 6.7). Rows are never edited or deleted - save() refuses to
    update an existing row and delete() is disabled outright, so `Trip.status`
    can be trusted to always be reconstructable from this table."""

    trip = models.ForeignKey(
        Trip, on_delete=models.CASCADE, related_name="status_history"
    )
    previous_status = models.CharField(max_length=30)
    new_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="trip_status_changes"
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["changed_at", "id"]
        verbose_name_plural = "Trip status histories"

    def __str__(self) -> str:
        return f"Trip {self.trip_id}: {self.previous_status} -> {self.new_status}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "TripStatusHistory records are immutable and cannot be edited."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "TripStatusHistory records are immutable and cannot be deleted."
        )
