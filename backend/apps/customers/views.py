from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "sales"
