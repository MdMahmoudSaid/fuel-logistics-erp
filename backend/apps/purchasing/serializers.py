from decimal import Decimal
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.serializers import ProductSerializer
from apps.documents.serializers import DocumentSerializer
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.services import SupplierOrderAmendmentService, SupplierStockService
from apps.suppliers.serializers import SupplierSerializer


class CessionLetterSerializer(serializers.ModelSerializer):
    loaded_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    created_by_detail = UserSerializer(source="created_by", read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)

    class Meta:
        model = CessionLetter
        fields = [
            "id",
            "reference",
            "supplier_order",
            "authorized_quantity",
            "issue_date",
            "status",
            "notes",
            "created_by",
            "created_by_detail",
            "loaded_quantity",
            "remaining_quantity",
            "documents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "reference", "created_by", "created_at", "updated_at"]

    def get_loaded_quantity(self, obj) -> str:
        loaded = obj.authorized_quantity - SupplierStockService.get_cession_remaining(obj)
        return f"{loaded:.2f}"

    def get_remaining_quantity(self, obj) -> str:
        remaining = SupplierStockService.get_cession_remaining(obj)
        return f"{remaining:.2f}"

    def validate(self, data):
        supplier_order = data.get("supplier_order")
        if not supplier_order and self.instance:
            supplier_order = self.instance.supplier_order

        authorized_quantity = data.get("authorized_quantity")
        if authorized_quantity is None and self.instance:
            authorized_quantity = self.instance.authorized_quantity

        if supplier_order and authorized_quantity is not None:
            try:
                # Verrouille et valide via le service dans un bloc atomique
                SupplierStockService.validate_and_lock_reliquat(
                    purchase_id=supplier_order.id,
                    requested_qty=authorized_quantity,
                    exclude_cession_id=self.instance.id if self.instance else None,
                )
            except ValueError as exc:
                raise serializers.ValidationError({"authorized_quantity": str(exc)})

        return data


class SupplierOrderSerializer(serializers.ModelSerializer):
    reliquat = serializers.SerializerMethodField()
    loaded_quantity = serializers.SerializerMethodField()
    supplier_detail = SupplierSerializer(source="supplier", read_only=True)
    product_detail = ProductSerializer(source="product", read_only=True)
    created_by_detail = UserSerializer(source="created_by", read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)
    cessions = CessionLetterSerializer(many=True, read_only=True)
    # Write-only: why a CONFIRMED order's amount is being amended. Never a
    # model column - it goes to the audit trail (see update()).
    reason = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = SupplierOrder
        fields = [
            "id",
            "reference",
            "supplier",
            "supplier_detail",
            "product",
            "product_detail",
            "purchase_date",
            "quantity_litres",
            "unit_price",
            "currency",
            "total_amount",
            "optional_costs",
            "notes",
            "status",
            "created_by",
            "created_by_detail",
            "reliquat",
            "loaded_quantity",
            "documents",
            "cessions",
            "reason",
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

    # Fields whose values determine total_amount, and therefore what an
    # AdvanceConsumption row was computed against. Once the order is
    # CONFIRMED they can still be corrected (client request 2026-09-24), but
    # only with a written reason and only if SupplierOrderAmendmentService
    # accepts the change.
    _FINANCIAL_FIELDS = ["quantity_litres", "unit_price", "optional_costs"]

    def validate(self, data):
        instance = self.instance
        if instance is None or instance.status != SupplierOrder.Status.CONFIRMED:
            return data
        changed = [
            field
            for field in self._FINANCIAL_FIELDS
            if field in data and data[field] != getattr(instance, field)
        ]
        if not changed:
            return data

        errors = {}
        if not (data.get("reason") or "").strip():
            errors["reason"] = (
                "Un motif est obligatoire pour modifier la quantité, le prix ou les "
                "coûts d'une commande confirmée."
            )
        new_quantity = data.get("quantity_litres", instance.quantity_litres)
        new_total = SupplierOrder.compute_total(
            new_quantity,
            data.get("unit_price", instance.unit_price),
            data.get("optional_costs", instance.optional_costs),
        )
        errors.update(
            SupplierOrderAmendmentService.validate(
                instance, new_quantity=new_quantity, new_total=new_total
            )
        )
        if errors:
            raise serializers.ValidationError(errors)
        return data

    def create(self, validated_data):
        validated_data.pop("reason", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        reason = (validated_data.pop("reason", "") or "").strip() or None
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        # Not super().update(): it calls save() bare, which would drop the
        # reason before AuditableModel.save can put it on the audit log.
        instance.save(reason=reason)
        return instance

    def get_reliquat(self, obj) -> str:
        reliquat = SupplierStockService.get_purchase_reliquat(obj)
        return f"{reliquat:.2f}"

    def get_loaded_quantity(self, obj) -> str:
        loaded = SupplierStockService.get_purchase_loaded_quantity(obj)
        return f"{loaded:.2f}"
