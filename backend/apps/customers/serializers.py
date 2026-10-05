from decimal import Decimal

from django.db.models import Sum, Max
from rest_framework import serializers

from .models import Customer


class CustomerBriefSerializer(serializers.ModelSerializer):
    """A customer embedded in another record (trip, sale, invoice...):
    identity only. Its running totals live on the customer's own page -
    recomputing them for every embedded row made each list page cost
    several queries per row."""

    class Meta:
        model = Customer
        fields = [
            "id", "name", "company_name", "phone", "address",
            "contact_name", "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = fields

class CustomerSerializer(serializers.ModelSerializer):
    total_invoiced = serializers.SerializerMethodField()
    total_collected = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    open_invoices_count = serializers.SerializerMethodField()
    last_payment_date = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id", "name", "company_name", "phone", "address",
            "contact_name", "notes", "total_invoiced", "total_collected",
            "outstanding_balance", "open_invoices_count", "last_payment_date",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_total_invoiced(self, obj) -> str:
        total = obj.sales.aggregate(total=Sum("invoice__total_amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_total_collected(self, obj) -> str:
        # Excludes is_reversed=True (Phase 5: a cancelled indirect
        # settlement's synthetic payment must not still count as collected).
        total = (
            obj.payments.exclude(is_reversed=True).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        return f"{total:.2f}"

    def get_outstanding_balance(self, obj) -> str:
        invoiced = Decimal(self.get_total_invoiced(obj))
        collected = Decimal(self.get_total_collected(obj))
        return f"{max(invoiced - collected, Decimal('0.00')):.2f}"

    def get_open_invoices_count(self, obj) -> int:
        return obj.sales.filter(invoice__status__in=["VALIDATED", "PARTIALLY_PAID"]).count()

    def get_last_payment_date(self, obj) -> str:
        return obj.payments.aggregate(date=Max("payment_date"))["date"] or ""
