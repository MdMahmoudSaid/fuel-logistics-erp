from rest_framework import generics, viewsets
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated

from apps.accounts.permissions import HasModulePermission

from .models import LossToleranceConfig, Product
from .serializers import LossToleranceConfigSerializer, ProductSerializer


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


class LossToleranceConfigView(generics.RetrieveUpdateAPIView):
    """docs/PHASE_4_PLAN.md Etape 6: GET|PATCH /api/settings/loss-tolerance/,
    restricted to the "admin" module (plan: "gestion de la tolerance par un
    administrateur").

    Not a ModelViewSet: LossToleranceConfig is a singleton (guide Section
    7.4/plan Etape 1), so there is no list to expose - GET/PATCH always
    target the one row (or an unsaved stand-in showing the spec default
    before any admin has ever configured it).
    """

    serializer_class = LossToleranceConfigSerializer
    permission_classes = [HasModulePermission]
    module = "admin"

    @property
    def action(self):
        # HasModulePermission reads view.action (a ViewSet concept) - this
        # is a plain generics.APIView, so translate the HTTP verb into the
        # same "view"/"edit" vocabulary Role.ACTIONS uses.
        return "view" if self.request.method in SAFE_METHODS else "edit"

    def get_object(self):
        config = LossToleranceConfig.objects.first()
        if config is None:
            # Nobody has ever saved a row - show the spec's 100 L default
            # (LossToleranceConfig.DEFAULT_TOLERANCE) without persisting
            # anything on a bare GET.
            config = LossToleranceConfig(tolerance_litres=LossToleranceConfig.DEFAULT_TOLERANCE)
        self.check_object_permissions(self.request, config)
        return config

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
