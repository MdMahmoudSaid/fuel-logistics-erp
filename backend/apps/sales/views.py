from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import CustomerOrder
from .serializers import CustomerOrderSerializer


class CustomerOrderViewSet(viewsets.ModelViewSet):
    queryset = CustomerOrder.objects.all()
    serializer_class = CustomerOrderSerializer
    filterset_fields = ["customer", "product", "status"]
    permission_classes = [HasModulePermission]
    module = "sales"

    @action(detail=True, methods=["get"])
    def trips(self, request, pk=None):
        """All trips fulfilling this order.

        GET /api/customer-orders/{id}/trips/
        """
        # Imported lazily: sales sits below trips in the app dependency
        # graph (apps.trips.services imports apps.sales.services), so a
        # module-level import here would run in the reverse direction.
        from apps.trips.serializers import TripSerializer

        order = self.get_object()
        trips = order.trips.all()
        return Response(
            TripSerializer(trips, many=True, context={"request": request}).data
        )
