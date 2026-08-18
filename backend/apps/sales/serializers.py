from rest_framework import serializers

from apps.core.serializers import ProductSerializer
from apps.customers.serializers import CustomerSerializer
from apps.sales.models import CustomerOrder
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
