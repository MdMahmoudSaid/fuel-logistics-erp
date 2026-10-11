from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from apps.customers.serializers import CustomerBriefSerializer

from .models import (
    DeliveryNote,
    DeliveryNoteLine,
    LoadingSheet,
    LoadingSheetLine,
    PurchaseOrderDocument,
    PurchaseOrderLine,
)

_READ_ONLY = ["id", "reference", "created_by", "created_at", "updated_at"]


class BaseDocumentSerializer(serializers.ModelSerializer):
    """Nested lines, replaced as a whole on every write (same rule as
    QuotationSerializer). Subclasses set `line_fk`, the line -> document
    foreign key name."""

    line_fk = ""

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Au moins une ligne est requise.")
        return lines

    def _sync_lines(self, document, lines):
        model = self.fields["lines"].child.Meta.model
        document.lines.all().delete()
        for position, data in enumerate(lines):
            model.objects.create(**{self.line_fk: document}, position=position, **data)
        self.after_lines(document)

    def after_lines(self, document):
        pass

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        document = super().create(validated_data)
        self._sync_lines(document, lines)
        return document

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        document = super().update(instance, validated_data)
        if lines is not None:
            self._sync_lines(document, lines)
        return document


class DeliveryNoteLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryNoteLine
        fields = ["id", "trip", "designation", "quantity", "tanker", "tractor", "missing", "observation"]
        read_only_fields = ["id"]


class DeliveryNoteSerializer(BaseDocumentSerializer):
    line_fk = "note"
    customer_detail = CustomerBriefSerializer(source="customer", read_only=True)
    lines = DeliveryNoteLineSerializer(many=True)
    total_quantity = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryNote
        fields = _READ_ONLY + [
            "date", "customer", "customer_detail", "place", "delivery_address", "notes", "lines",
            "total_quantity",
        ]
        read_only_fields = _READ_ONLY

    def get_total_quantity(self, obj) -> str:
        return str(sum((line.quantity for line in obj.lines.all()), Decimal("0.00")))


class LoadingSheetLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoadingSheetLine
        fields = ["id", "truck", "tractor", "tanker", "capacity_litres", "product_name", "be_number", "route"]
        read_only_fields = ["id"]

    def validate(self, data):
        if not (data.get("truck") or data.get("tractor") or data.get("tanker")):
            raise serializers.ValidationError({"tractor": "Indiquez un camion, un tracteur ou une citerne."})
        return data


class LoadingSheetSerializer(BaseDocumentSerializer):
    line_fk = "sheet"
    supplier_display_name = serializers.CharField(read_only=True)
    lines = LoadingSheetLineSerializer(many=True)
    total_litres = serializers.SerializerMethodField()

    class Meta:
        model = LoadingSheet
        fields = _READ_ONLY + [
            "date", "supplier", "supplier_name", "supplier_display_name", "on_behalf_of", "source_reference",
            "product_name", "route", "notes", "lines", "total_litres",
        ]
        read_only_fields = _READ_ONLY

    def get_total_litres(self, obj) -> str:
        total = sum((line.capacity_litres for line in obj.lines.all()), Decimal("0.00"))
        return f"{total:.2f}"

    def validate(self, data):
        supplier = data.get("supplier", getattr(self.instance, "supplier", None))
        name = data.get("supplier_name", getattr(self.instance, "supplier_name", ""))
        if not supplier and not name:
            raise serializers.ValidationError({"supplier_name": "Indiquez le fournisseur ou le dépôt."})
        return data


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "product", "description", "quantity", "unit", "unit_price", "line_total"]
        read_only_fields = ["id", "line_total"]

    def validate(self, data):
        if not data.get("product") and not data.get("description"):
            raise serializers.ValidationError({"description": "Indiquez un produit ou une description."})
        return data


class PurchaseOrderDocumentSerializer(BaseDocumentSerializer):
    line_fk = "order"
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseOrderLineSerializer(many=True)

    class Meta:
        model = PurchaseOrderDocument
        fields = _READ_ONLY + [
            "date", "supplier", "supplier_name", "supplier_order", "delivery_place", "delivery_date",
            "payment_terms", "currency", "status", "total_amount", "notes", "lines",
        ]
        read_only_fields = _READ_ONLY + ["total_amount"]

    def after_lines(self, document):
        document.total_amount = document.lines.aggregate(total=Sum("line_total"))["total"] or Decimal("0.00")
        document.save(update_fields=["total_amount", "updated_at"])
