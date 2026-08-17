from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import BankAccount, CashAccount
from .serializers import BankAccountSerializer, CashAccountSerializer


class BankAccountViewSet(viewsets.ModelViewSet):
    queryset = BankAccount.objects.all()
    serializer_class = BankAccountSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "finance"


class CashAccountViewSet(viewsets.ModelViewSet):
    queryset = CashAccount.objects.all()
    serializer_class = CashAccountSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "finance"
