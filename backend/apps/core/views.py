from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import HasModulePermission

from .models import Product
from .serializers import ProductSerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    filterset_fields = ["is_active"]
    module = "operations"

    def get_permissions(self):
        # Product is shared reference data (Purchasing, Sales and Operations
        # all need it as a lookup - e.g. SupplierOrder.product) rather than
        # something that belongs to one module. Gating list/retrieve behind
        # "operations" view rights silently broke purchase-order creation for
        # any role scoped to purchasing without also holding operations
        # rights - caught by the Phase 2 Section 3.B manual UAT run with a
        # Purchasing-only role. Reads: any authenticated user. Writes
        # (create/edit/delete a product definition): still operations-only.
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [HasModulePermission()]
