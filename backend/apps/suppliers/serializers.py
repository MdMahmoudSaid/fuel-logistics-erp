from decimal import Decimal

from django.db.models import Max, Sum
from rest_framework import serializers

from apps.purchasing.services import SupplierStockService

from .models import Supplier


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
        total = obj.orders.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_total_paid(self, obj) -> str:
        total = obj.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_outstanding_balance(self, obj) -> str:
        purchased = Decimal(self.get_total_purchased(obj))
        paid = Decimal(self.get_total_paid(obj))
        return f"{max(purchased - paid, Decimal('0.00')):.2f}"

    def get_total_reliquat(self, obj) -> str:
        total = sum(
            (SupplierStockService.get_purchase_reliquat(order) for order in obj.orders.all()),
            Decimal("0.00"),
        )
        return f"{total:.2f}"

    def get_last_payment_date(self, obj) -> str:
        return obj.payments.aggregate(date=Max("payment_date"))["date"] or ""
