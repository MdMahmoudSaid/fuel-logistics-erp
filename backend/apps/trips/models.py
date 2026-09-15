from decimal import Decimal

from django.db import models

from apps.audit.mixins import AuditableModel
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
        ROAD_TRANSIT = "ROAD_TRANSIT", "Road transit"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        BORDER = "BORDER", "Border"
        CUSTOMS = "CUSTOMS", "Customs"
        GOING_TO_COMPANY_STOCK = "GOING_TO_COMPANY_STOCK", "Going to company stock"
        ARRIVED_AT_COMPANY_STOCK = (
            "ARRIVED_AT_COMPANY_STOCK",
            "Arrived at company stock",
        )
        STOCKED = "STOCKED", "Stocked"
        GOING_TO_CLIENT = "GOING_TO_CLIENT", "Going to client"
        ARRIVED_AT_CLIENT = "ARRIVED_AT_CLIENT", "Arrived at client"
        QUANTITY_CONTROL = "QUANTITY_CONTROL", "Quantity control"
        DELIVERED = "DELIVERED", "Delivered"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
        CANCELLED = "CANCELLED", "Cancelled"

    # A trip in either of these statuses is finished for good (never
    # reopened, excluded from the active status board, etc.).
    TERMINAL_STATUSES = {Status.COMPLETED, Status.CANCELLED}

    # For the narrower purpose of "does this trip still occupy its truck/
    # transporter for a NEW assignment" (TruckAvailabilityService /
    # TransporterAvailabilityService), DELIVERED also releases the
    # resource: the load has physically arrived and the truck is empty and
    # free, even if nobody has clicked through the administrative
    # DELIVERED -> COMPLETED step yet. Deliberately NOT folded into
    # TERMINAL_STATUSES, which other rules (is_active(), CANCELLABLE_FROM,
    # the active status board) rely on staying just {COMPLETED, CANCELLED}.
    #
    # Bug fix (2026-09-03 recette manuelle): STOCKED used to also be
    # included here, freeing the truck the moment a trip reached "stock
    # entreprise / stocke" - but a trip's fuel sitting in company stock is
    # not the same as the truck having actually completed a delivery. The
    # client's rule: a truck stays occupied through every active status
    # (including STOCKED/GOING_TO_CLIENT/ARRIVED_AT_CLIENT/
    # QUANTITY_CONTROL) - only DELIVERED (or a terminal status) frees it.
    NON_OCCUPYING_STATUSES = TERMINAL_STATUSES | {Status.DELIVERED}

    class DestinationType(models.TextChoices):
        """Makes the "no client, no customer order" state a first-class,
        queryable value (client's most important structural request - see
        docs/plan.md Global Constraints) rather than something only
        inferrable by checking `client is None and customer_order is None`.
        Never mandatory at trip creation: a trip with neither is a valid,
        common state (fuel routed to company stock, sold/assigned later)."""

        COMPANY_STOCK = "COMPANY_STOCK", "Stock de l'entreprise"
        CUSTOMER = "CUSTOMER", "Client"

    reference = models.CharField(max_length=100, unique=True)
    truck = models.ForeignKey(
        "transport.Truck", on_delete=models.PROTECT, related_name="trips"
    )
    # Bug fix (2026-09-03 recette manuelle): always auto-derived from
    # truck.owner_transporter (TripSerializer._validate_and_derive_transporter)
    # - every Truck now has one, real for EXTERNAL or the seeded
    # is_internal=True row for COMPANY_OWNED (reverses Phase 6's original
    # "no artificial internal transporter" rule). Stays null=True at the DB
    # level only for backward compatibility with trips created before this
    # fix; application code never creates a new one without a transporter.
    transporter = models.ForeignKey(
        "transport.Transporter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="trips",
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
    destination_type = models.CharField(
        max_length=20,
        choices=DestinationType.choices,
        default=DestinationType.COMPANY_STOCK,
    )
    loading_date = models.DateField()
    bl_reference = models.CharField(max_length=100)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.ASSIGNED
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="trips_created"
    )

    class Meta:
        ordering = ["-loading_date", "-id"]
        indexes = [
            models.Index(fields=["destination_type"]),
            models.Index(fields=["client"]),
            models.Index(fields=["customer_order"]),
            models.Index(fields=["loading_date"]),
        ]
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


class DeliveryControl(AuditableModel, TimeStampedModel):
    """Quantity control recorded at discharge, the source of commercial
    truth for the whole downstream chain (docs/PHASE_4_PLAN.md Etape 2;
    ERP_Implementation_Experience_Guide.md Section 7.2/7.3: "Delivery is not
    simply trip.status = DELIVERED - it should record evidence and
    operational data").

    loss_quantity and chargeable_loss_quantity are always recomputed from
    loaded/received/tolerance on save() (same pattern as
    SupplierOrder.total_amount) rather than trusted as caller input, so they
    can never drift from the three source values.

    tolerance_quantity freezes the LossToleranceConfig value that was in
    effect at confirmation time (guide Section 7.2's "gel historique" rule):
    once written here it must never be touched again even if the global
    default changes later.
    """

    class Method(models.TextChoices):
        MANUAL_GAUGE = "MANUAL_GAUGE", "Manual gauge"
        METER = "METER", "Meter"

    trip = models.OneToOneField(
        Trip, on_delete=models.PROTECT, related_name="delivery_control"
    )
    loaded_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    loss_quantity = models.DecimalField(
        max_digits=14, decimal_places=2, editable=False
    )
    tolerance_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    chargeable_loss_quantity = models.DecimalField(
        max_digits=14, decimal_places=2, editable=False
    )
    control_date = models.DateField()
    controller = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="delivery_controls"
    )
    method = models.CharField(max_length=20, choices=Method.choices)
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_controls",
    )
    notes = models.TextField(blank=True)
    anomaly_confirmed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confirmed_delivery_anomalies",
    )
    anomaly_confirmed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateField(
        null=True, blank=True,
        help_text="Date a laquelle la quantite recue a ete verifiee/corrigee "
        "par le client, distincte de control_date (date de livraison initiale).",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(loaded_quantity__gt=0),
                name="trips_deliverycontrol_loaded_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(received_quantity__gte=0),
                name="trips_deliverycontrol_received_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(tolerance_quantity__gte=0),
                name="trips_deliverycontrol_tolerance_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Delivery control for {self.trip.reference}"

    def save(self, *args, **kwargs):
        # Quantity Formula (guide Section 7.3): loss can go negative when
        # received > loaded (the anomaly case) - chargeable_loss floors at 0
        # either way, it is never a debt owed by the client.
        loss = self.loaded_quantity - self.received_quantity
        self.loss_quantity = loss
        self.chargeable_loss_quantity = max(
            loss - self.tolerance_quantity, Decimal("0.00")
        )
        super().save(*args, **kwargs)

    @property
    def company_absorbed_loss_quantity(self) -> Decimal:
        """Portion de la perte non facturable au transporteur (<= tolerance),
        supportee par l'entreprise (client modifications 2026-09-04)."""
        return max(self.loss_quantity, Decimal("0.00")) - self.chargeable_loss_quantity


class ClientVerificationCorrection(models.Model):
    """Append-only audit trail entry for a correction to an already-recorded
    client verification (feedback 2026-09-10: the "Declarer une perte"
    button primed operators to type the loss instead of the received
    quantity, and DeliveryService.record_client_verification() deliberately
    refuses a second call rather than silently overwrite the first
    declaration - see its docstring). Mirrors
    apps.sales.models.InvoiceCorrection's "previous/new value + reason +
    actor" shape.

    Written exclusively by DeliveryService.correct_client_verification()
    under the same Trip row lock as the original verification.
    """

    trip = models.ForeignKey(
        Trip, on_delete=models.CASCADE, related_name="verification_corrections"
    )
    previous_received_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    new_received_quantity = models.DecimalField(max_digits=14, decimal_places=2)
    corrected_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="client_verification_corrections",
    )
    corrected_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    class Meta:
        ordering = ["-corrected_at", "-id"]

    def __str__(self) -> str:
        return (
            f"{self.trip.reference}: {self.previous_received_quantity} -> "
            f"{self.new_received_quantity}"
        )
