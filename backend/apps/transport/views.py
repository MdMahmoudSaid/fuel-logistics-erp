from rest_framework import viewsets

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
