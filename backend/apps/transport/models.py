from django.db import models

from apps.core.models import TimeStampedModel


class Transporter(TimeStampedModel):
    name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

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
    owner_transporter = models.ForeignKey(
        Transporter, null=True, blank=True, on_delete=models.SET_NULL, related_name="trucks"
    )
    default_driver = models.ForeignKey(
        Driver, null=True, blank=True, on_delete=models.SET_NULL, related_name="trucks"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["internal_id"]

    def __str__(self) -> str:
        return self.internal_id


# Truck, Transporter, Driver models: see roadmap/phase_1_foundation.md.
# Trip, TripStatusHistory live in a separate `trips` app added in Phase 3
# (see roadmap/phase_3_truck_operations.md).
