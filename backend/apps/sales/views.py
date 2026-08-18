from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import CustomerOrder, Invoice, Sale
from .serializers import CustomerOrderSerializer, InvoiceSerializer, SaleSerializer
from .services import (
    InvoiceNotValidated,
    InvoiceService,
    InvoiceValidationError,
    UnsupportedCorrectionField,
)


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


class SaleViewSet(viewsets.ModelViewSet):
    """List/retrieve only in practice (docs/PHASE_4_PLAN.md Etape 6): a Sale
    is generated exclusively by DeliveryService.record_delivery() (POST
    /api/trips/{id}/delivery-control/), so delivered_quantity can never
    drift from the confirming DeliveryControl.received_quantity (guide
    Section 7.6/§19).

    A plain ReadOnlyModelViewSet would leave POST/PATCH/DELETE unrouted
    entirely - but HasModulePermission.has_permission() runs before DRF
    would notice there's no handler for the method, so it 403s instead of
    405ing (view.action is None for an unrouted verb, which never matches
    any role's permission list). Overriding each verb explicitly here keeps
    the response an honest 405 with a clear reason, for every role.
    """

    queryset = Sale.objects.select_related("customer", "product", "trip").all()
    serializer_class = SaleSerializer
    filterset_fields = ["customer", "product", "trip"]
    permission_classes = [HasModulePermission]
    module = "sales"

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed(
            "POST",
            detail=(
                "Les ventes sont generees automatiquement lors de la "
                "confirmation de livraison "
                "(POST /api/trips/{id}/delivery-control/)."
            ),
        )

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed(
            "PATCH",
            detail="Une vente n'est jamais modifiee directement - voir POST /api/invoices/{id}/correct/.",
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(
            "DELETE",
            detail="La suppression directe est desactivee pour preserver l'historique financier.",
        )


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = (
        Invoice.objects.select_related("sale", "sale__customer")
        .prefetch_related("corrections")
        .all()
    )
    serializer_class = InvoiceSerializer
    filterset_fields = ["status", "sale"]
    permission_classes = [HasModulePermission]
    module = "sales"

    def create(self, request, *args, **kwargs):
        # Invoices are generated automatically alongside their Sale by
        # DeliveryService - never created directly (same reasoning as
        # SaleViewSet above).
        raise MethodNotAllowed(
            "POST",
            detail=(
                "Les factures sont generees automatiquement lors de la "
                "confirmation de livraison "
                "(POST /api/trips/{id}/delivery-control/)."
            ),
        )

    def destroy(self, request, *args, **kwargs):
        # Same audit-trail-preservation convention as TripViewSet.destroy()
        # (guide Section 17): financial history is never hard-deleted.
        raise MethodNotAllowed(
            "DELETE",
            detail="La suppression directe est desactivee pour preserver l'historique financier.",
        )

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        """Freeze this invoice's financial data.

        POST /api/invoices/{id}/validate/
        """
        invoice = self.get_object()
        try:
            invoice = InvoiceService.validate_invoice(invoice.id, request.user)
        except InvoiceValidationError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        """Adjust a validated invoice's price/amount under audit.

        POST /api/invoices/{id}/correct/  body: {field, new_value, reason}
        """
        invoice = self.get_object()
        field = request.data.get("field")
        new_value = request.data.get("new_value")
        reason = request.data.get("reason")
        if not field or new_value in (None, "") or not reason:
            return Response(
                {"detail": "field, new_value et reason sont requis."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        try:
            invoice = InvoiceService.correct_invoice(
                invoice.id, field, new_value, reason, request.user
            )
        except (InvoiceNotValidated, UnsupportedCorrectionField) as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(InvoiceSerializer(invoice, context={"request": request}).data)
