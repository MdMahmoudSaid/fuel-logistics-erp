from decimal import Decimal

from django.db import models

from apps.core.models import TimeStampedModel


class Quotation(TimeStampedModel):
    """Commercial offer ("Offre commerciale" / "Devis") - AZUR ÉNERGIE
    product decision 2026-09-05.

    Deliberately standalone: unlike CustomerOrder/Sale/Invoice, nothing
    reads a Quotation to create a Sale, Invoice, TreasuryTransaction or
    stock movement, and nothing here reads those either - a Quotation is a
    document a salesperson prints and hands to a prospect, never a step in
    the delivery/accounting pipeline. total_amount is the only derived
    field, recomputed from `lines` by QuotationSerializer whenever the
    lines change (there is no single-model save() hook for it, since the
    lines live on a separate related model - see that serializer's
    _sync_lines()).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"

    reference = models.CharField(max_length=50, unique=True)
    # Both optional individually, but never both blank at once (see the
    # CheckConstraint below) - "existing customer optional, free temporary
    # customer name allowed" (product decision 2026-09-05).
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quotations",
    )
    customer_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField()
    validity_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=10, default="XOF")
    total_amount = models.DecimalField(
        max_digits=16, decimal_places=2, editable=False, default=Decimal("0.00")
    )
    notes = models.TextField(blank=True)
    # Proforma (spec 2026-10-11 documents-commerciaux §3).
    payment_terms = models.CharField(max_length=255, blank=True)
    show_bank_accounts = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="quotations"
    )

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(customer__isnull=False) | ~models.Q(customer_name=""),
                name="quotations_quotation_customer_or_name_required",
            ),
        ]

    def __str__(self) -> str:
        return self.reference

    @property
    def customer_display_name(self) -> str:
        return self.customer.name if self.customer_id else self.customer_name


class QuotationLine(models.Model):
    """One priced row on a Quotation - product is optional (a quotation can
    quote a free-text service/description that isn't in the Product
    catalogue), but at least one of product/description must be set so the
    row is never blank on the printed PDF (see the CheckConstraint)."""

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "core.Product",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quotation_lines",
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    line_total = models.DecimalField(max_digits=16, decimal_places=2, editable=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="quotations_quotationline_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="quotations_quotationline_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(product__isnull=False) | ~models.Q(description=""),
                name="quotations_quotationline_product_or_description_required",
            ),
        ]

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.description or (self.product.name if self.product_id else f"Ligne {self.pk}")
