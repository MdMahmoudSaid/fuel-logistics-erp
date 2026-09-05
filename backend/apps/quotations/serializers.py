from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from apps.core.serializers import ProductSerializer
from apps.customers.serializers import CustomerSerializer

from .models import Quotation, QuotationLine


class QuotationLineSerializer(serializers.ModelSerializer):
    product_detail = ProductSerializer(source="product", read_only=True)

    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "product",
            "product_detail",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "line_total",
        ]
        read_only_fields = ["id", "line_total"]

    def validate(self, data):
        product = data.get("product")
        description = data.get("description", "")
        if not product and not description:
            raise serializers.ValidationError(
                {"description": "Indiquez un produit ou une description."}
            )
        return data


class QuotationSerializer(serializers.ModelSerializer):
    """docs/superpowers - AZUR ÉNERGIE quotation feature (2026-09-05).

    `lines` is a writable nested list (full replace on every write - see
    _sync_lines()): a quotation is a short, low-stakes document edited as a
    whole from one form, unlike CustomerPayment's allocations which need
    incremental history. total_amount is never accepted from the client -
    always recomputed server-side from the actually-saved lines so it can
    never drift from their sum.
    """

    customer_detail = CustomerSerializer(source="customer", read_only=True)
    lines = QuotationLineSerializer(many=True)

    class Meta:
        model = Quotation
        fields = [
            "id",
            "reference",
            "customer",
            "customer_detail",
            "customer_name",
            "status",
            "issue_date",
            "validity_date",
            "currency",
            "total_amount",
            "notes",
            "lines",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "reference",
            "total_amount",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        customer = data.get("customer", getattr(self.instance, "customer", None))
        customer_name = data.get("customer_name", getattr(self.instance, "customer_name", ""))
        if not customer and not customer_name:
            raise serializers.ValidationError(
                {
                    "customer_name": (
                        "Indiquez un client existant ou un nom de client temporaire."
                    )
                }
            )
        lines = data.get("lines")
        if lines is not None and len(lines) == 0:
            raise serializers.ValidationError({"lines": "Au moins une ligne est requise."})
        return data

    def _sync_lines(self, quotation: Quotation, lines_data: list[dict]) -> None:
        quotation.lines.all().delete()
        for line_data in lines_data:
            QuotationLine.objects.create(quotation=quotation, **line_data)
        total = quotation.lines.aggregate(total=Sum("line_total"))["total"] or Decimal("0.00")
        quotation.total_amount = total
        quotation.save(update_fields=["total_amount", "updated_at"])

    @transaction.atomic
    def create(self, validated_data: dict) -> Quotation:
        lines_data = validated_data.pop("lines")
        quotation = Quotation.objects.create(**validated_data)
        self._sync_lines(quotation, lines_data)
        return quotation

    @transaction.atomic
    def update(self, instance: Quotation, validated_data: dict) -> Quotation:
        lines_data = validated_data.pop("lines", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines_data is not None:
            self._sync_lines(instance, lines_data)
        return instance
