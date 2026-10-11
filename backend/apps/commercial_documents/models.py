# Commercial documents (spec 2026-10-11 documents-commerciaux §4-§6): the
# delivery note (customer), the loading sheet (supplier/depot that loads the
# trucks) and the purchase order (supplier). Printable documents only:
# nothing in accounting, stock, treasury or trips reads them.

from decimal import Decimal

from django.db import models

from apps.core.models import TimeStampedModel


class BaseDocument(TimeStampedModel):
    reference = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return self.reference


class BaseLine(models.Model):
    position = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["position", "id"]


class DeliveryNote(BaseDocument):
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="delivery_notes"
    )
    place = models.CharField(max_length=100, blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)


class DeliveryNoteLine(BaseLine):
    note = models.ForeignKey(DeliveryNote, on_delete=models.CASCADE, related_name="lines")
    trip = models.ForeignKey(
        "trips.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="delivery_note_lines"
    )
    designation = models.CharField(max_length=150)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    tanker = models.CharField(max_length=30, blank=True)
    tractor = models.CharField(max_length=30, blank=True)
    missing = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    observation = models.CharField(max_length=255, blank=True)

    class Meta(BaseLine.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="commercial_documents_deliverynoteline_quantity_positive"
            ),
        ]

    @staticmethod
    def from_trip(trip) -> dict:
        """Pre-filled line for a delivered trip: received quantity and loss
        from its delivery control, loaded quantity when it has none."""
        try:
            control = trip.delivery_control
        except Exception:  # RelatedObjectDoesNotExist
            control = None
        return {
            "trip": trip.id,
            "designation": trip.product.name.upper(),
            "quantity": control.received_quantity if control else trip.quantity_loaded,
            "tanker": trip.truck.tanker_registration,
            "tractor": trip.truck.tractor_registration,
            "missing": control.loss_quantity if control else None,
        }


class LoadingSheet(BaseDocument):
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="loading_sheets"
    )
    supplier_name = models.CharField(max_length=150, blank=True)
    on_behalf_of = models.CharField(max_length=150, blank=True)
    source_reference = models.CharField(max_length=100, blank=True)
    product_name = models.CharField(max_length=100, blank=True)
    route = models.CharField(max_length=100, blank=True)

    class Meta(BaseDocument.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(supplier__isnull=False) | ~models.Q(supplier_name=""),
                name="commercial_documents_loadingsheet_supplier_required",
            ),
        ]

    @property
    def supplier_display_name(self) -> str:
        return self.supplier.name if self.supplier_id else self.supplier_name


class LoadingSheetLine(BaseLine):
    sheet = models.ForeignKey(LoadingSheet, on_delete=models.CASCADE, related_name="lines")
    truck = models.ForeignKey("transport.Truck", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    tractor = models.CharField(max_length=30, blank=True)
    tanker = models.CharField(max_length=30, blank=True)
    capacity_litres = models.DecimalField(max_digits=10, decimal_places=2)
    product_name = models.CharField(max_length=100, blank=True)
    be_number = models.CharField(max_length=50, blank=True)
    route = models.CharField(max_length=100, blank=True)

    class Meta(BaseLine.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity_litres__gt=0),
                name="commercial_documents_loadingsheetline_capacity_positive",
            ),
        ]


class PurchaseOrderDocument(BaseDocument):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"

    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="purchase_order_documents"
    )
    supplier_order = models.ForeignKey(
        "purchasing.SupplierOrder", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    delivery_place = models.CharField(max_length=150, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=10, default="XOF")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"), editable=False)


class PurchaseOrderLine(BaseLine):
    order = models.ForeignKey(PurchaseOrderDocument, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("core.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    line_total = models.DecimalField(max_digits=16, decimal_places=2, editable=False)

    class Meta(BaseLine.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="commercial_documents_purchaseorderline_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="commercial_documents_purchaseorderline_price_non_negative",
            ),
        ]

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
