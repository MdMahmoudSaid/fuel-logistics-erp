from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import Product
from .serializers import ProductSerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "operations"
