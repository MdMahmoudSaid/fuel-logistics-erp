from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.date_range import resolve_date_range
from apps.reports.serialization import decimals_to_str
from apps.reports.services.ledger_pdf import (
    render_customer_payment_pdf,
    render_supplier_payment_pdf,
    render_trip_settlement_pdf,
)
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter
from apps.trips.models import Trip

from .models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseCategory,
    Shareholder,
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderWithdrawal,
    SupplierAdvance,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from .serializers import (
    BankAccountSerializer,
    CashAccountSerializer,
    ControlledDebtPaymentRequestSerializer,
    CustomerPaymentSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    IndirectSettlementRequestSerializer,
    ShareholderContributionSerializer,
    ShareholderLoanSerializer,
    ShareholderProfitDistributionSerializer,
    ShareholderSerializer,
    ShareholderWithdrawalSerializer,
    SupplierAdvanceSerializer,
    SupplierPaymentSerializer,
    TransporterAdvanceSerializer,
    TransportPaymentSerializer,
    TreasuryTransactionSerializer,
    TreasuryTransferRequestSerializer,
)
from .services import (
    ControlledDebtPaymentError,
    ControlledDebtPaymentService,
    ExpenseCancellationError,
    ExpensePostingService,
    IndirectSettlementService,
    PaymentAllocationError,
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderProfitPreviewService,
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

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        """Per-payment PDF for one CustomerPayment (recette corrections
        2026-09-05, Section 2) - Grand livre client now has the same
        per-row PDF action Grand livre transporteur already had.

        GET /api/customer-payments/{id}/pdf/?lang=fr|en|ar
        """
        payment = self.get_object()
        lang = request.query_params.get("lang", "fr")
        pdf_bytes = render_customer_payment_pdf(payment, lang=lang)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="paiement-client-{payment.id}.pdf"'
        return response


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

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        """Per-payment PDF for one SupplierPayment (recette corrections
        2026-09-05, Section 2) - Grand livre fournisseur now has the same
        per-row PDF action Grand livre transporteur already had.

        GET /api/supplier-payments/{id}/pdf/?lang=fr|en|ar
        """
        payment = self.get_object()
        lang = request.query_params.get("lang", "fr")
        pdf_bytes = render_supplier_payment_pdf(payment, lang=lang)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="paiement-fournisseur-{payment.id}.pdf"'
        return response


class SupplierAdvanceViewSet(viewsets.ModelViewSet):
    queryset = SupplierAdvance.objects.select_related("supplier", "bank_account", "cash_account").all()
    serializer_class = SupplierAdvanceSerializer
    filterset_fields = ["supplier"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def perform_create(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


class TransporterAdvanceViewSet(viewsets.ModelViewSet):
    queryset = TransporterAdvance.objects.select_related("transporter", "bank_account", "cash_account").all()
    serializer_class = TransporterAdvanceSerializer
    filterset_fields = ["transporter"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def perform_create(self, serializer):
        serializer.save()

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

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        """Per-trip settlement PDF ("Reglement par trajet") - Task 11.
        Export/formatting only: prints the already-loaded TransportPayment/
        Trip fields via render_trip_settlement_pdf, no new calculation.

        GET /api/transport-payments/{id}/pdf/?lang=fr|en|ar
        """
        payment = self.get_object()
        lang = request.query_params.get("lang", "fr")
        pdf_bytes = render_trip_settlement_pdf(payment, lang=lang)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="reglement-{payment.trip.reference}.pdf"'
        return response


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.prefetch_related("allocations").all()
    serializer_class = ExpenseSerializer
    filterset_fields = ["category", "status", "paid_by_customer_directly"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def get_queryset(self):
        # ?trip=<id>: expenses allocated to one trip (TripDetail's "Frais du
        # trajet" tab) - Expense has no direct FK to Trip, only the generic
        # ExpenseAllocation link, so this can't be a plain filterset field
        # (same generic-FK lookup TripProfitService._expense_allocations uses).
        queryset = super().get_queryset()
        trip_id = self.request.query_params.get("trip")
        if trip_id:
            trip_content_type = ContentType.objects.get_for_model(Trip)
            queryset = queryset.filter(
                allocations__content_type=trip_content_type, allocations__object_id=trip_id
            ).distinct()
        if self.request.query_params.get("unallocated") == "true":
            queryset = queryset.filter(allocations__isnull=True)
        return queryset

    def destroy(self, request, *args, **kwargs):
        # Bug fix (2026-09-03 recette manuelle): an UNPAID Expense has no
        # accounting impact yet (no TreasuryTransaction, no
        # IndirectSettlement CustomerPayment) - a hard delete is safe and
        # was always the intended behavior (Phase 5 design doc: "Non paye:
        # modification/suppression autorisee sans changement"), unlike
        # every other model sharing _NO_HARD_DELETE_DETAIL. PAID/
        # PARTIALLY_PAID/CANCELLED still go through /cancel/ only.
        expense = self.get_object()
        if expense.status != Expense.Status.UNPAID:
            raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Reverse a PAID/PARTIALLY_PAID Expense (Phase 5, docs/superpowers/
        specs/2026-09-02-business-corrections-6-phases-design.md): the only
        way to unwind a fee once payment has moved, since PATCH blocks its
        sensitive fields past that point.

        POST /api/expenses/{id}/cancel/
        """
        expense = self.get_object()
        try:
            expense = ExpensePostingService.cancel_paid_expense(expense, request.user)
        except ExpenseCancellationError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context={"request": request}).data)

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


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    filterset_fields = ["is_system", "is_active"]
    permission_classes = [HasModulePermission]
    module = "finance"

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system:
            return Response(
                {"detail": "Une categorie systeme ne peut pas etre supprimee."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


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

    @action(detail=False, methods=["get"], url_path="payable-debts")
    def payable_debts(self, request):
        """List unpaid or partially paid debts for the controlled outgoing
        payment workflow.

        GET /api/treasury-transactions/payable-debts/?debt_type=supplier
        """
        debt_type = request.query_params.get("debt_type")
        if debt_type not in ControlledDebtPaymentService.supported_debt_types():
            return Response(
                {"detail": "Type de dette inconnu."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        try:
            debts = ControlledDebtPaymentService.get_payable_debts(debt_type)
        except ControlledDebtPaymentError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(decimals_to_str(debts))

    @action(detail=False, methods=["get"], url_path="party-balances")
    def party_balances(self, request):
        """Single source of truth for net_balance per supplier/transporter -
        consumed by the Nouvelle avance / Nouveau paiement button logic
        everywhere (Journal, Grands livres) and must never disagree with
        the Dashboard or Grand livre summary cards.

        GET /api/treasury-transactions/party-balances/?debt_type=supplier|transporter
        """
        debt_type = request.query_params.get("debt_type")
        if debt_type == ControlledDebtPaymentService.SUPPLIER:
            rows = [
                ControlledDebtPaymentService.describe_supplier_balance(supplier)
                for supplier in Supplier.objects.filter(is_active=True).order_by("name", "id")
            ]
        elif debt_type == ControlledDebtPaymentService.TRANSPORTER:
            rows = [
                ControlledDebtPaymentService.describe_transporter_balance(transporter)
                for transporter in Transporter.objects.filter(is_active=True).order_by("name", "id")
            ]
        else:
            return Response({"detail": "Type de tiers inconnu."}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(decimals_to_str(rows))

    @action(detail=False, methods=["post"], url_path="record-debt-payment")
    def record_debt_payment(self, request):
        """Create one bank MONEY_OUT tied to an existing payable debt.

        POST /api/treasury-transactions/record-debt-payment/
        """
        request_serializer = ControlledDebtPaymentRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data

        try:
            result = ControlledDebtPaymentService.record_payment(
                debt_type=data["debt_type"],
                debt_id=data["debt_id"],
                bank_account_id=data["bank_account"],
                amount=data["amount"],
                date=data["date"],
                reference=data["reference"],
                actor=request.user,
                note=data["note"],
                attachment=data["attachment"],
            )
        except ControlledDebtPaymentError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(
            decimals_to_str(
                {
                    "transaction": TreasuryTransactionSerializer(
                        result["transaction"], context={"request": request}
                    ).data if result["transaction"] is not None else None,
                    "transactions": TreasuryTransactionSerializer(
                        result.get("transactions", []), many=True, context={"request": request}
                    ).data,
                    "debt": result["debt"],
                    "bank_balance_before": result["bank_balance_before"],
                    "bank_balance_after": result["bank_balance_after"],
                }
            ),
            status=http_status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Task 7 (client modifications plan): Shareholders / Associates domain
# ---------------------------------------------------------------------------


class ShareholderViewSet(viewsets.ModelViewSet):
    # total_contributed annotated here (rather than a per-row aggregate in
    # the serializer) so the Associes list page doesn't run N extra queries
    # to show each shareholder's real capital apporte (bug fix, 2026-09-03
    # recette manuelle - see ShareholderSerializer.total_contributed).
    queryset = Shareholder.objects.annotate(
        total_contributed=Coalesce(Sum("contributions__amount"), Decimal("0.00"))
    )
    serializer_class = ShareholderSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "shareholders"

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Per-shareholder summary: profit shares/remaining due, loans in
        both directions, withdrawal history (Task 7, client modifications
        plan; precedent: SupplierViewSet.ledger).

        GET /api/shareholders/{id}/ledger/
        """
        shareholder = self.get_object()
        summary = ShareholderLedgerService.get_shareholder_summary(shareholder.id)
        return Response(decimals_to_str(summary))

    @action(detail=False, methods=["get"], url_path="profit-preview")
    def profit_preview(self, request):
        """Read-only, indicative current-profit split across active
        shareholders, computed from the existing profit engine - never a
        stored figure and never gates a withdrawal (design doc
        2026-08-26-benefices-associes-refinement-design.md).

        GET /api/shareholders/profit-preview/?from=&to=
        """
        date_from, date_to = resolve_date_range(request.query_params)
        preview = ShareholderProfitPreviewService.get_preview(
            date_from=date_from, date_to=date_to
        )
        return Response(decimals_to_str(preview))


class ShareholderProfitDistributionViewSet(viewsets.ModelViewSet):
    queryset = ShareholderProfitDistribution.objects.select_related(
        "created_by", "validated_by"
    ).prefetch_related("shares__shareholder").all()
    serializer_class = ShareholderProfitDistributionSerializer
    filterset_fields = ["status"]
    permission_classes = [HasModulePermission]
    module = "shareholders"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        """Freeze a DRAFT distribution's shares.

        POST /api/shareholder-distributions/{id}/validate/
        """
        distribution = self.get_object()
        distribution = ShareholderDistributionService.validate_distribution(
            distribution.id, request.user
        )
        return Response(
            ShareholderProfitDistributionSerializer(distribution, context={"request": request}).data
        )


class ShareholderLoanViewSet(viewsets.ModelViewSet):
    queryset = ShareholderLoan.objects.select_related("borrower", "lender").all()
    serializer_class = ShareholderLoanSerializer
    filterset_fields = ["borrower", "lender", "status"]
    permission_classes = [HasModulePermission]
    module = "shareholders"

    @action(detail=True, methods=["post"], url_path="record-repayment")
    def record_repayment(self, request, pk=None):
        """Increment amount_repaid under a row lock (Task 7 fix:
        loan-repayment lost-update race) - amount_repaid is read-only on
        the plain update endpoint precisely so every repayment must go
        through this atomic increment instead of a client-computed
        absolute total that could silently overwrite a concurrent one.

        POST /api/shareholder-loans/{id}/record-repayment/  body: {amount}
        """
        loan = self.get_object()
        amount = request.data.get("amount")
        if amount in (None, ""):
            return Response(
                {"detail": "amount est requis."}, status=http_status.HTTP_400_BAD_REQUEST
            )
        try:
            loan = ShareholderLoanService.record_repayment(loan.id, amount)
        except ShareholderLoanError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(ShareholderLoanSerializer(loan, context={"request": request}).data)


class ShareholderWithdrawalViewSet(viewsets.ModelViewSet):
    queryset = ShareholderWithdrawal.objects.select_related(
        "shareholder", "profit_share", "bank_account", "cash_account", "recorded_by"
    ).all()
    serializer_class = ShareholderWithdrawalSerializer
    filterset_fields = ["shareholder", "profit_share"]
    permission_classes = [HasModulePermission]
    module = "shareholders"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


class ShareholderContributionViewSet(viewsets.ModelViewSet):
    queryset = ShareholderContribution.objects.select_related(
        "shareholder", "bank_account", "cash_account", "recorded_by"
    ).all()
    serializer_class = ShareholderContributionSerializer
    filterset_fields = ["shareholder"]
    permission_classes = [HasModulePermission]
    module = "shareholders"

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)


# Entity kinds ExpenseAllocation.content_object can point at (guide Section
# 8.7: "split across several trips, trucks, customers, suppliers or
# transporters"). (app_label, model) matches each model's Django default
# app_label/model_name - see ContentType.objects.get_for_model().
_ALLOCATABLE_KINDS = [
    ("trip", "trips", "trip"),
    ("truck", "transport", "truck"),
    ("customer", "customers", "customer"),
    ("supplier", "suppliers", "supplier"),
    ("transporter", "transport", "transporter"),
]


class AllocatableTypesViewSet(viewsets.ViewSet):
    """Read-only lookup from entity kind to its ContentType PK, so the
    frontend expense-allocation picker can resolve a human choice (e.g.
    "Trip") to the numeric content_type ExpenseAllocationInputSerializer
    expects - nothing else exposes that mapping.

    GET /api/allocatable-types/
    """

    permission_classes = [HasModulePermission]
    module = "finance"

    def list(self, request):
        data = [
            {
                "kind": kind,
                "content_type": ContentType.objects.get(app_label=app_label, model=model).id,
            }
            for kind, app_label, model in _ALLOCATABLE_KINDS
        ]
        return Response(data)
