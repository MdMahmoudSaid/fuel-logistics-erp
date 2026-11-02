from django.db import models

from apps.core.models import TimeStampedModel


class Customer(TimeStampedModel):
    name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    # "Client de passage": created per direct sale with the name typed in the
    # attribution popup, paid in full cash at invoicing. Hidden from customer
    # lists and receivables (see CustomerViewSet.get_queryset).
    is_walk_in = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
