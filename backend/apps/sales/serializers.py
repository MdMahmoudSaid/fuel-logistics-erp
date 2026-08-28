from django.db.models import Sum
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.serializers import ProductSerializer
from apps.customers.serializers import CustomerSerializer
from apps.documents.models import Document
from apps.finance.models import CustomerPayment
from apps.sales.models import CustomerOrder, Invoice, InvoiceCorrection, Sale
from apps.sales.services import CustomerOrderService

# Statuses a caller may set directly via the API. PARTIALLY_ASSIGNED /
# IN_PROGRESS / PARTIALLY_DELIVERED / DELIVERED are derived exclusively by
# CustomerOrderService.recompute_status() from trip progress - allowing a
# direct PATCH into one of them would let an order show e.g. "Delivered"
# while its trips disagree (docs/PHASE_3_PLAN.md Etape 5;
# roadmap/phase_3_truck_operations.md: "prevents an order showing
# 'Delivered' while trips disagree").
_MANUALLY_SETTABLE_STATUSES = {
    CustomerOrder.Status.DRAFT,
    CustomerOrder.Status.CONFIRMED,
    CustomerOrder.Status.CLOSED,
    CustomerOrder.Status.CANCELLED,
}


class CustomerOrderSerializer(serializers.ModelSerializer):
    customer_detail = CustomerSerializer(source="customer", read_only=True)
    product_detail = ProductSerializer(source="product", read_only=True)
    assigned_quantity = serializers.SerializerMethodField()
    loaded_quantity = serializers.SerializerMethodField()
    delivered_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = CustomerOrder
        fields = [
            "id",
            "customer",
            "customer_detail",
            "product",
            "product_detail",
            "quantity_ordered",
            "expected_price",
            "status",
            "notes",
            "assigned_quantity",
            "loaded_quantity",
            "delivered_quantity",
            "remaining_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_assigned_quantity(self, obj) -> str:
        return f"{CustomerOrderService.get_assigned_quantity(obj):.2f}"

    def get_loaded_quantity(self, obj) -> str:
        return f"{CustomerOrderService.get_loaded_quantity(obj):.2f}"

    def get_delivered_quantity(self, obj) -> str:
        return f"{CustomerOrderService.get_delivered_quantity(obj):.2f}"

    def get_remaining_quantity(self, obj) -> str:
        return f"{CustomerOrderService.get_remaining_quantity(obj):.2f}"

    def validate_status(self, value):
        if value not in _MANUALLY_SETTABLE_STATUSES:
            raise serializers.ValidationError(
                f"Le statut '{value}' est calcule automatiquement a partir des "
                "trajets et ne peut pas etre defini directement."
            )
        return value


class SaleSerializer(serializers.ModelSerializer):
    """Read-only representation (docs/PHASE_4_PLAN.md Etape 6;
    ERP_Implementation_Experience_Guide.md Section 7.6/§19): a Sale is
    created exclusively by DeliveryService.record_delivery() so
    delivered_quantity can never drift from the confirming
    DeliveryControl.received_quantity - see SaleViewSet for the enforcement.

    trip_reference (a plain string) is exposed instead of a nested
    TripSerializer: apps.sales sits below apps.trips in the app dependency
    graph (apps.trips.services already imports apps.sales.services/models),
    so a module-level import of apps.trips.serializers here would run the
    dependency the wrong way round.
    """

    customer_detail = CustomerSerializer(source="customer", read_only=True)
    product_detail = ProductSerializer(source="product", read_only=True)
    trip_reference = serializers.CharField(source="trip.reference", read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "trip",
            "trip_reference",
            "customer",
            "customer_detail",
            "product",
            "product_detail",
            "delivered_quantity",
            "unit_selling_price",
            "currency",
            "subtotal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class InvoiceCorrectionSerializer(serializers.ModelSerializer):
    """Read-only audit trail entry (guide Section 21) - always written by
    InvoiceService.correct_invoice(), never directly through the API."""

    corrected_by_detail = UserSerializer(source="corrected_by", read_only=True)

    class Meta:
        model = InvoiceCorrection
        fields = [
            "id",
            "field_name",
            "previous_value",
            "new_value",
            "corrected_by",
            "corrected_by_detail",
            "corrected_at",
            "reason",
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    """docs/PHASE_4_PLAN.md Etape 6.

    invoice_number/sale/status are read-only: invoice_number and sale are
    fixed at creation by DeliveryService, and status only ever moves through
    InvoiceViewSet's validate action (InvoiceService.validate_invoice) -
    same "no direct write to a state machine field" convention as
    Trip.status/TripWorkflowService.

    total_amount/issued_date stay directly editable while DRAFT (plan
    Section 1.E: only a *validated* invoice's financial data is frozen) -
    validate() below is what enforces that boundary.
    """

    sale_detail = SaleSerializer(source="sale", read_only=True)
    corrections = InvoiceCorrectionSerializer(many=True, read_only=True)
    paid_amount = serializers.SerializerMethodField()
    outstanding_amount = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "sale",
            "sale_detail",
            "status",
            "total_amount",
            "paid_amount",
            "outstanding_amount",
            "issued_date",
            "corrections",
            "payments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "invoice_number",
            "sale",
            "sale_detail",
            "status",
            "paid_amount",
            "outstanding_amount",
            "corrections",
            "payments",
            "created_at",
            "updated_at",
        ]

    def get_paid_amount(self, obj) -> str:
        paid = obj.allocations.aggregate(total=Sum("amount"))["total"] or 0
        return f"{paid:.2f}"

    def get_outstanding_amount(self, obj) -> str:
        paid = obj.allocations.aggregate(total=Sum("amount"))["total"] or 0
        return f"{max(obj.total_amount - paid, 0):.2f}"

    def get_payments(self, obj) -> list[dict]:
        content_type = ContentType.objects.get_for_model(CustomerPayment)
        rows = []
        allocations = obj.allocations.select_related("payment").order_by(
            "-payment__payment_date", "-payment_id"
        )
        for allocation in allocations:
            payment = allocation.payment
            document = (
                Document.objects.filter(
                    content_type=content_type,
                    object_id=payment.id,
                    document_type="customer_payment_proof",
                )
                .order_by("-created_at", "-id")
                .first()
            )
            rows.append(
                {
                    "id": payment.id,
                    "payment_date": payment.payment_date.isoformat(),
                    "method": payment.method,
                    "reference": payment.reference,
                    "amount": f"{allocation.amount:.2f}",
                    "proof_url": document.file.url if document and document.file else None,
                }
            )
        return rows

    def validate(self, data):
        if (
            self.instance
            and self.instance.status == Invoice.Status.VALIDATED
            and data
        ):
            raise serializers.ValidationError(
                "Cette facture est validee - toute modification directe est "
                "bloquee. Utilisez POST /api/invoices/{id}/correct/ pour "
                "l'ajuster sous audit."
            )
        return data
