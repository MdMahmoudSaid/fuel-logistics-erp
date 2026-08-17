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


# Truck, Transporter, Driver models: see roadmap/phase_1_foundation.md.
# Trip, TripStatusHistory live in a separate `trips` app added in Phase 3
# (see roadmap/phase_3_truck_operations.md).
