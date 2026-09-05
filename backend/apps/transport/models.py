from django.db import models

from apps.core.models import TimeStampedModel


class Transporter(TimeStampedModel):
    name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    # Bug fix (2026-09-03 recette manuelle): every Truck must be linked to
    # a transporter, even when it belongs to the company - rather than
    # leaving Truck.owner_transporter/Trip.transporter null for that case
    # (Phase 6's original rule), a single is_internal=True row ("Flotte
    # propre / Interne", seeded by migration) stands in for the company's
    # own fleet. Never gets a real TransportPayment/TransportDeduction
    # posted against it (see DeliveryService.sync_transport_shortage_deduction,
    # TransportPaymentSerializer.validate) - kept purely for traceability/
    # display, exactly like a real transporter would show on a trip.
    is_internal = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Driver(TimeStampedModel):
    """Optional-by-design (§10): only `name` is required. A missing driver
    must never block truck/trip operations."""

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    license_number = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Truck(TimeStampedModel):
    class OwnershipType(models.TextChoices):
        COMPANY_OWNED = "COMPANY_OWNED", "Company owned"
        EXTERNAL = "EXTERNAL", "External / rented"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        ON_TRIP = "ON_TRIP", "On trip"
        BLOCKED = "BLOCKED", "Blocked"

    internal_id = models.CharField(max_length=30, unique=True)
    tractor_registration = models.CharField(max_length=30)
    tanker_registration = models.CharField(max_length=30)
    capacity_litres = models.DecimalField(max_digits=10, decimal_places=2)
    ownership_type = models.CharField(
        max_length=20, choices=OwnershipType.choices, default=OwnershipType.COMPANY_OWNED
    )
    # Bug fix (2026-09-03 recette manuelle): mandatory in every case now -
    # EXTERNAL keeps its real transporter, COMPANY_OWNED gets the seeded
    # is_internal=True row (TruckSerializer.validate() auto-assigns it when
    # left blank). PROTECT rather than the previous SET_NULL: a transporter
    # can no longer be deleted out from under a truck now that the field is
    # required (see the migration that adds this field for the
    # backfill of any pre-existing COMPANY_OWNED truck left null).
    owner_transporter = models.ForeignKey(
        Transporter, on_delete=models.PROTECT, related_name="trucks"
    )
    default_driver = models.ForeignKey(
        Driver, null=True, blank=True, on_delete=models.SET_NULL, related_name="trucks"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["internal_id"]

    def save(self, *args, **kwargs):
        # Bug fix (2026-09-03 recette manuelle): defends the "no truck
        # without a transporter" invariant at the model layer, not just in
        # TruckSerializer - a COMPANY_OWNED truck created directly (a
        # script, the Django admin, a test fixture) gets the seeded
        # internal transporter here too, so the DB's NOT NULL constraint on
        # owner_transporter is never the first place this gets caught.
        # EXTERNAL stays unassisted - there is no sane default external
        # transporter, so that case is expected to fail loudly instead.
        if self.owner_transporter_id is None and self.ownership_type == self.OwnershipType.COMPANY_OWNED:
            # UI recette fix (2026-09-05): is_internal became user-editable
            # via TransporterSerializer (several internal transporters are
            # now expected, not just the one seeded row) - .get() would
            # crash with MultipleObjectsReturned the moment a second one
            # exists. TransporterSerializer.validate() only guarantees "at
            # least one" survives, so this can still legitimately find none
            # if the seed migration was never applied - fail loudly with a
            # clear message rather than a bare DoesNotExist either way.
            transporter = Transporter.objects.filter(is_internal=True).first()
            if transporter is None:
                raise ValueError(
                    "Aucun transporteur interne (flotte propre) n'existe pour "
                    "assigner ce camion appartenant a l'entreprise."
                )
            self.owner_transporter = transporter
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.internal_id


# Truck, Transporter, Driver models: see roadmap/phase_1_foundation.md.
# Trip, TripStatusHistory live in a separate `trips` app added in Phase 3
# (see roadmap/phase_3_truck_operations.md).
