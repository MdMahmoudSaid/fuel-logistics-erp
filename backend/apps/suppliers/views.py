from decimal import Decimal
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    filterset_fields = ["is_active", "country"]
    permission_classes = [HasModulePermission]
    module = "purchasing"

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Endpoint to get supplier purchase ledger.

        GET /api/suppliers/{id}/ledger/
        """
        supplier = self.get_object()
        from apps.purchasing.models import SupplierOrder
        from apps.purchasing.serializers import SupplierOrderSerializer
        from apps.purchasing.services import SupplierStockService

        orders = SupplierOrder.objects.filter(supplier=supplier)
        orders_serialized = SupplierOrderSerializer(orders, many=True).data

        # Agrégation du reliquat par produit
        product_reliquats = {}
        for order in orders:
            product_id = order.product.id
            product_name = order.product.name
            reliquat = SupplierStockService.get_purchase_reliquat(order)

            if product_id not in product_reliquats:
                product_reliquats[product_id] = {
                    "product_id": product_id,
                    "product_name": product_name,
                    "total_reliquat": Decimal("0.00"),
                }
            product_reliquats[product_id]["total_reliquat"] += reliquat

        reliquat_summary = []
        for item in product_reliquats.values():
            reliquat_summary.append(
                {
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "total_reliquat": f"{item['total_reliquat']:.2f}",
                }
            )

        return Response(
            {
                "supplier": {
                    "id": supplier.id,
                    "name": supplier.name,
                },
                "orders": orders_serialized,
                "reliquat_summary": reliquat_summary,
            }
        )

