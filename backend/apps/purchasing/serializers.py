from decimal import Decimal
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.serializers import ProductSerializer
from apps.documents.serializers import DocumentSerializer
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.services import SupplierStockService
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
    # AdvanceConsumption row was computed against - frozen once the order is
    # CONFIRMED (docs/superpowers/plans/2026-09-01-supplier-transporter-
    # advances.md, final review): the only way to change the amount is the
    # explicit cancellation workflow (status=CANCELLED reverses any
    # consumption), never an in-place edit of a confirmed order.
    _FINANCIAL_FIELDS = ["quantity_litres", "unit_price", "optional_costs"]

    def validate(self, data):
        if self.instance is not None and self.instance.status == SupplierOrder.Status.CONFIRMED:
            for field in self._FINANCIAL_FIELDS:
                if field in data and data[field] != getattr(self.instance, field):
                    raise serializers.ValidationError(
                        {
                            field: (
                                "Ce champ ne peut plus etre modifie une fois la commande "
                                "confirmee. Annulez la commande (statut CANCELLED) si le "
                                "montant doit changer."
                            )
                        }
                    )
        return data

    def get_reliquat(self, obj) -> str:
        reliquat = SupplierStockService.get_purchase_reliquat(obj)
        return f"{reliquat:.2f}"

    def get_loaded_quantity(self, obj) -> str:
        loaded = SupplierStockService.get_purchase_loaded_quantity(obj)
        return f"{loaded:.2f}"
