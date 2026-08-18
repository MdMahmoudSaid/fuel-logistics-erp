from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "sales"

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Customer account statement: invoices, payments received and the
        outstanding receivable balance (docs/PHASE_5_PLAN.md Etape 8;
        guide Section 8.3/8.4).

        GET /api/customers/{id}/ledger/
        """
        # Imported lazily: apps.customers sits below apps.sales/apps.finance
        # in the app dependency graph (both already import
        # apps.customers.serializers.CustomerSerializer), so a module-level
        # import here would run the dependency the wrong way round.
        from apps.finance.serializers import CustomerPaymentSerializer
        from apps.finance.services import PaymentAllocationService
        from apps.sales.models import Invoice
        from apps.sales.serializers import InvoiceSerializer

        customer = self.get_object()
        invoices = Invoice.objects.filter(sale__customer=customer).select_related(
            "sale", "sale__customer"
        )
        payments = customer.payments.select_related(
            "bank_account", "cash_account", "recorded_by"
        ).prefetch_related("allocations")

        return Response(
            {
                "customer": CustomerSerializer(customer).data,
                "outstanding_balance": f"{PaymentAllocationService.get_customer_outstanding(customer):.2f}",
                "invoices": InvoiceSerializer(invoices, many=True, context={"request": request}).data,
                "payments": CustomerPaymentSerializer(payments, many=True, context={"request": request}).data,
            }
        )
