from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from .serializers import (
    BankAccountSerializer,
    CashAccountSerializer,
    CustomerPaymentSerializer,
    ExpenseSerializer,
    IndirectSettlementRequestSerializer,
    SupplierPaymentSerializer,
    TransporterAdvanceSerializer,
    TransportPaymentSerializer,
    TreasuryTransactionSerializer,
    TreasuryTransferRequestSerializer,
)
from .services import (
    IndirectSettlementService,
    PaymentAllocationError,
    TreasuryService,
    TreasuryTransferError,
)

# Once money has actually moved or been committed to a specific invoice,
# these records become audit trail (guide Section 8.12: "avoid physical
# deletion; cancel/reverse instead") - same convention as Sale/Invoice.
_NO_HARD_DELETE_DETAIL = (
    "La suppression directe est desactivee pour preserver l'historique financier."
)


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


class CustomerPaymentViewSet(viewsets.ModelViewSet):
    queryset = CustomerPayment.objects.select_related(
        "customer", "bank_account", "cash_account", "recorded_by"
    ).prefetch_related("allocations").all()
    serializer_class = CustomerPaymentSerializer
    filterset_fields = ["customer", "is_indirect", "method"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except PaymentAllocationError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except PaymentAllocationError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


class SupplierPaymentViewSet(viewsets.ModelViewSet):
    queryset = SupplierPayment.objects.select_related(
        "supplier", "supplier_order", "bank_account", "cash_account", "recorded_by"
    ).all()
    serializer_class = SupplierPaymentSerializer
    filterset_fields = ["supplier", "supplier_order", "is_advance"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


class TransporterAdvanceViewSet(viewsets.ModelViewSet):
    queryset = TransporterAdvance.objects.select_related("transporter").all()
    serializer_class = TransporterAdvanceSerializer
    filterset_fields = ["transporter", "settled"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


class TransportPaymentViewSet(viewsets.ModelViewSet):
    queryset = TransportPayment.objects.select_related(
        "trip", "transporter", "advance_applied"
    ).all()
    serializer_class = TransportPaymentSerializer
    filterset_fields = ["trip", "transporter", "status"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.prefetch_related("allocations").all()
    serializer_class = ExpenseSerializer
    filterset_fields = ["category", "status", "paid_by_customer_directly"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=False, methods=["post"], url_path="record-indirect")
    def record_indirect(self, request):
        """Customer-paid operational expense (docs/PHASE_5_PLAN.md Etape 6/7;
        guide Section 1.6/8.9): reduces the customer's receivable and marks
        the expense paid, without ever moving company treasury.

        POST /api/expenses/record-indirect/
        """
        request_serializer = IndirectSettlementRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data

        try:
            expense, payment, allocation = IndirectSettlementService.record_indirect_payment(
                customer_id=data["customer"],
                expense_data={
                    "category": data["category"],
                    "amount": data["amount"],
                    "calculation_method": data["calculation_method"],
                    "date": data["date"],
                    "reference": data["reference"],
                    "notes": data["notes"],
                },
                actor=request.user,
                invoice_id=data["invoice"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "expense": ExpenseSerializer(expense, context={"request": request}).data,
                "payment": CustomerPaymentSerializer(payment, context={"request": request}).data,
                "allocation_id": allocation.id,
            },
            status=http_status.HTTP_201_CREATED,
        )


class TreasuryTransactionViewSet(viewsets.ModelViewSet):
    queryset = TreasuryTransaction.objects.select_related(
        "bank_account", "cash_account", "document", "recorded_by"
    ).all()
    serializer_class = TreasuryTransactionSerializer
    filterset_fields = ["bank_account", "cash_account", "type"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=False, methods=["post"])
    def transfer(self, request):
        """Internal transfer between two treasury accounts, recorded as a
        matched MONEY_OUT/MONEY_IN pair (docs/PHASE_5_PLAN.md Etape 6/8;
        guide Section 8.10/D).

        POST /api/treasury-transactions/transfer/
        """
        request_serializer = TreasuryTransferRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data

        try:
            out_txn, in_txn = TreasuryService.record_transfer(
                source_account_type=data["source_account_type"],
                source_account_id=data["source_account_id"],
                dest_account_type=data["dest_account_type"],
                dest_account_id=data["dest_account_id"],
                amount=data["amount"],
                date=data["date"],
                reference=data["reference"],
                user=request.user,
            )
        except TreasuryTransferError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "money_out": TreasuryTransactionSerializer(out_txn, context={"request": request}).data,
                "money_in": TreasuryTransactionSerializer(in_txn, context={"request": request}).data,
            },
            status=http_status.HTTP_201_CREATED,
        )
