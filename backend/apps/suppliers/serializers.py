from decimal import Decimal

from django.db.models import Max, Sum
from rest_framework import serializers

from apps.purchasing.models import SupplierOrder
from apps.purchasing.services import SupplierStockService

from .models import Supplier


class SupplierBriefSerializer(serializers.ModelSerializer):
    """A supplier embedded in another record: identity only (see
    CustomerBriefSerializer)."""

    class Meta:
        model = Supplier
        fields = [
            "id", "name", "company_name", "country", "phone",
            "contact_name", "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = fields

class SupplierSerializer(serializers.ModelSerializer):
    total_purchased = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    total_reliquat = serializers.SerializerMethodField()
    last_payment_date = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            "id", "name", "company_name", "country", "phone",
            "contact_name", "notes", "total_purchased", "total_paid",
            "outstanding_balance", "total_reliquat", "last_payment_date",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_total_purchased(self, obj) -> str:
        total = (
            obj.orders.filter(status=SupplierOrder.Status.CONFIRMED).aggregate(
                total=Sum("total_amount")
            )["total"]
            or Decimal("0.00")
        )
        return f"{total:.2f}"

    def get_total_paid(self, obj) -> str:
        # Task 6 (client business decision, confirmed 2026-09-06): a
        # cancelled (is_reversed=True) payment never really left treasury -
        # excluded so this figure reflects what's currently true.
        total = (
            obj.payments.exclude(is_reversed=True).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        return f"{total:.2f}"

    def get_outstanding_balance(self, obj) -> str:
        # Business rule reversal (client request, 2026-09-10): the debt
        # owed to a supplier is the full confirmed order total, due
        # immediately on confirmation - see
        # ControlledDebtPaymentService.describe_supplier_order
        # (apps.finance.services), which this must stay consistent with.
        total_purchased = Decimal(self.get_total_purchased(obj))
        paid = Decimal(self.get_total_paid(obj))
        return f"{max(total_purchased - paid, Decimal('0.00')):.2f}"

    def get_total_reliquat(self, obj) -> str:
        total = sum(
            (
                SupplierStockService.get_purchase_reliquat(order)
                for order in obj.orders.filter(status=SupplierOrder.Status.CONFIRMED)
            ),
            Decimal("0.00"),
        )
        return f"{total:.2f}"

    def get_last_payment_date(self, obj) -> str:
        return obj.payments.aggregate(date=Max("payment_date"))["date"] or ""
