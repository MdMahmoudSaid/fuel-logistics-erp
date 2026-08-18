from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import Driver, Transporter, Truck
from .serializers import DriverSerializer, TransporterSerializer, TruckSerializer


class TransporterViewSet(viewsets.ModelViewSet):
    queryset = Transporter.objects.all()
    serializer_class = TransporterSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "operations"


class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer
    permission_classes = [HasModulePermission]
    module = "operations"


class TruckViewSet(viewsets.ModelViewSet):
    queryset = Truck.objects.all()
    serializer_class = TruckSerializer
    filterset_fields = ["status", "ownership_type"]
    permission_classes = [HasModulePermission]
    module = "operations"

    @action(detail=True, methods=["get"])
    def trips(self, request, pk=None):
        """Full trip history for this physical truck (newest first).

        GET /api/trucks/{id}/trips/
        """
        # Imported lazily: transport sits below trips in the app dependency
        # graph (Trip.truck points here, not the reverse).
        from apps.trips.serializers import TripSerializer

        truck = self.get_object()
        trips = truck.trips.all()
        return Response(
            TripSerializer(trips, many=True, context={"request": request}).data
        )
