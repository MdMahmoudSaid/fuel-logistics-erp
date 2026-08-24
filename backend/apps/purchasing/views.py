from django.db import IntegrityError, transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.core.reference import generate_monthly_reference
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.serializers import CessionLetterSerializer, SupplierOrderSerializer
from apps.purchasing.services import SupplierStockService

# Purchasing records use a status field (DRAFT/CONFIRMED/CANCELLED,
# ACTIVE/EXHAUSTED/CANCELLED) instead of physical deletion, per
# ERP_Implementation_Experience_Guide.md §17 ("Cancellation and Reversal") and
# §5.7 ("decrementing supplier stock without trace" is an anti-pattern). A
# CessionLetter still consuming reliquat must never disappear silently - it
# has to go through PATCH {"status": "CANCELLED"} so the reliquat calculation
# and audit trail both see it.
_NO_HARD_DELETE_DETAIL = (
    "Direct deletion is disabled to preserve the audit trail. "
    "Set status to CANCELLED instead (PATCH)."
)


_SUPPLIER_ORDER_REFERENCE_PREFIX = "ACH"
_CESSION_LETTER_REFERENCE_PREFIX = "CES"
_MAX_REFERENCE_ATTEMPTS = 5


class SupplierOrderViewSet(viewsets.ModelViewSet):
    queryset = SupplierOrder.objects.all()
    serializer_class = SupplierOrderSerializer
    filterset_fields = ["supplier", "product", "status"]
    permission_classes = [HasModulePermission]
    module = "purchasing"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = generate_monthly_reference(
                SupplierOrder, "reference", _SUPPLIER_ORDER_REFERENCE_PREFIX
            )
            try:
                with transaction.atomic():
                    serializer.save(reference=reference, created_by=self.request.user)
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer une reference de commande fournisseur "
            f"unique apres {_MAX_REFERENCE_ATTEMPTS} tentatives."
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=True, methods=["get"])
    def reliquat(self, request, pk=None):
        """Endpoint to get the remaining unallocated quantity for a supplier order.

        GET /api/supplier-orders/{id}/reliquat/
        """
        order = self.get_object()
        reliquat = SupplierStockService.get_purchase_reliquat(order)
        return Response(
            {
                "supplier_order_id": order.id,
                "reference": order.reference,
                "quantity_litres": str(order.quantity_litres),
                "reliquat": f"{reliquat:.2f}",
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="next-reference")
    def next_reference(self, request):
        """Non-reserving preview of the reference the next created
        SupplierOrder will receive - for form display only, not a
        reservation. GET /api/supplier-orders/next-reference/
        """
        reference = generate_monthly_reference(
            SupplierOrder, "reference", _SUPPLIER_ORDER_REFERENCE_PREFIX
        )
        return Response({"reference": reference})


class CessionLetterViewSet(viewsets.ModelViewSet):
    queryset = CessionLetter.objects.all()
    serializer_class = CessionLetterSerializer
    filterset_fields = ["supplier_order", "status"]
    permission_classes = [HasModulePermission]
    module = "purchasing"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = generate_monthly_reference(
                CessionLetter, "reference", _CESSION_LETTER_REFERENCE_PREFIX
            )
            try:
                with transaction.atomic():
                    serializer.save(reference=reference, created_by=self.request.user)
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer une reference de lettre de cession "
            f"unique apres {_MAX_REFERENCE_ATTEMPTS} tentatives."
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=False, methods=["get"], url_path="next-reference")
    def next_reference(self, request):
        """Non-reserving preview of the reference the next created
        CessionLetter will receive. GET /api/cession-letters/next-reference/
        """
        reference = generate_monthly_reference(
            CessionLetter, "reference", _CESSION_LETTER_REFERENCE_PREFIX
        )
        return Response({"reference": reference})
