from django.db import IntegrityError, transaction
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.core.reference import generate_monthly_reference
from apps.reports.serialization import decimals_to_str
from apps.reports.services.profit import TripProfitService

from .models import Trip
from .serializers import (
    AssignCustomerRequestSerializer,
    DeliveryControlRequestSerializer,
    DeliveryControlSerializer,
    TripSerializer,
    TripStatusHistorySerializer,
)
from .services import (
    CustomerAlreadySoldError,
    DeliveryAnomalyConfirmationRequired,
    DeliveryService,
    InvalidTripTransition,
    SaleBelowCostConfirmationRequired,
    TripCostService,
    TripWorkflowService,
)

# Trip records use TripWorkflowService transitions (CANCELLED included)
# instead of physical deletion, per ERP_Implementation_Experience_Guide.md
# §17 - same convention as SupplierOrder/CessionLetter in apps.purchasing.
_NO_HARD_DELETE_DETAIL = (
    "La suppression directe est desactivee pour preserver l'historique. "
    "Utilisez POST /api/trips/{id}/status/ avec CANCELLED a la place."
)

_REFERENCE_PREFIX = "TRIP-"
_REFERENCE_WIDTH = 6
_MAX_REFERENCE_ATTEMPTS = 5


def _generate_next_reference() -> str:
    """Sequential, zero-padded reference (TRIP-000001, TRIP-000002, ...).

    There's no dedicated sequence table, so this reads the current highest
    reference and increments it; perform_create() retries on IntegrityError
    to cover the rare race between two concurrent creates picking the same
    number (cheaper than locking a counter row for an internal, non-
    negotiated identifier - unlike the truck/cession locks, which guard
    real business quantities).

    The regex restricts this to references matching our own generated
    format (fixed-width digits). Some trips carry hand-picked references
    (e.g. seeded fixtures) that also start with "TRIP-" but aren't
    numeric - ordering by "-reference" across those would pick a
    lexicographically-last string like "TRIP-TRANSPORT-R2", fail to parse
    as a number, and silently restart the sequence at TRIP-000001,
    colliding with an existing row on every retry.
    """
    last = (
        Trip.objects.filter(
            reference__regex=rf"^{_REFERENCE_PREFIX}\d{{{_REFERENCE_WIDTH}}}$"
        )
        .order_by("-reference")
        .first()
    )
    last_number = 0
    if last:
        try:
            last_number = int(last.reference.removeprefix(_REFERENCE_PREFIX))
        except ValueError:
            last_number = 0
    return f"{_REFERENCE_PREFIX}{last_number + 1:0{_REFERENCE_WIDTH}d}"


class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    filterset_fields = [
        "truck",
        "status",
        "customer_order",
        "client",
        "supplier_order",
        "cession_letter",
    ]
    permission_classes = [HasModulePermission]
    module = "operations"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        extra = {}
        if not serializer.validated_data.get("bl_reference"):
            extra["bl_reference"] = generate_monthly_reference(Trip, "bl_reference", "BL")
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = _generate_next_reference()
            try:
                with transaction.atomic():
                    serializer.save(
                        reference=reference, created_by=self.request.user, **extra
                    )
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer une reference de trajet unique apres "
            f"{_MAX_REFERENCE_ATTEMPTS} tentatives."
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail=_NO_HARD_DELETE_DETAIL)

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        """Transition this trip's status under the workflow service's lock.

        POST /api/trips/{id}/status/  body: {new_status, notes}
        """
        trip = self.get_object()
        new_status = request.data.get("new_status")
        notes = request.data.get("notes", "")

        if not new_status:
            return Response(
                {"new_status": "Ce champ est requis."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        try:
            trip = TripWorkflowService.transition_trip(
                trip.id, new_status, request.user, notes=notes
            )
        except InvalidTripTransition as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
            )

        return Response(TripSerializer(trip, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Full status timeline for this trip, oldest first.

        GET /api/trips/{id}/history/
        """
        trip = self.get_object()
        history = trip.status_history.all()
        return Response(TripStatusHistorySerializer(history, many=True).data)

    @action(detail=True, methods=["get"], url_path="allowed-statuses")
    def allowed_statuses(self, request, pk=None):
        trip = self.get_object()
        allowed = TripWorkflowService.get_allowed_targets(trip)
        return Response(
            {
                "statuses": [status for status in Trip.Status.values if status in allowed],
            }
        )

    @action(detail=True, methods=["get"])
    def margin(self, request, pk=None):
        """Revenue/cost breakdown behind this trip's current margin
        (TripProfitService.get_cost_breakdown, guide Section 9.1) -
        available once the trip has a Sale (delivery confirmed), not
        before, so this reports {"available": false} rather than an error
        for a trip still in progress.

        GET /api/trips/{id}/margin/
        """
        trip = self.get_object()
        if not hasattr(trip, "sale"):
            return Response({"available": False})
        breakdown = TripProfitService.get_cost_breakdown(trip)
        return Response({"available": True, **decimals_to_str(breakdown)})

    @action(detail=True, methods=["get"], url_path="cost-basis")
    def cost_basis(self, request, pk=None):
        """Fuel purchase cost, transport cost, allocated expenses (by
        category) and the resulting total/unit cost for this trip
        (TripCostService.calculate_trip_cost_basis) - available from the
        moment a trip is loaded, unlike /margin/ which needs a Sale.

        GET /api/trips/{id}/cost-basis/
        """
        trip = self.get_object()
        cost_basis = TripCostService.calculate_trip_cost_basis(trip)
        return Response(decimals_to_str(cost_basis))

    @action(detail=True, methods=["post"], url_path="assign-customer")
    def assign_customer(self, request, pk=None):
        """Attach/replace this trip's direct customer
        (TripCostService.assign_customer_for_sale) - rejected once the
        trip already has a Sale.

        POST /api/trips/{id}/assign-customer/  body: {customer}
        """
        trip = self.get_object()
        input_serializer = AssignCustomerRequestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        customer = input_serializer.validated_data["customer"]

        try:
            trip = TripCostService.assign_customer_for_sale(
                trip.id, customer.id, request.user
            )
        except CustomerAlreadySoldError as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
            )

        return Response(TripSerializer(trip, context={"request": request}).data)

    @action(detail=True, methods=["get"], url_path="suggested-selling-price")
    def suggested_selling_price(self, request, pk=None):
        """Latest applicable ProductSellingPriceHistory price for this
        trip's product/customer (DeliveryService.get_latest_selling_price),
        used to pre-fill the delivery form's "Prix de vente unitaire"
        field. `null` when no customer is resolvable yet or nothing is on
        file - the field is then left for the user to fill in by hand.

        GET /api/trips/{id}/suggested-selling-price/
        """
        trip = self.get_object()
        customer = trip.client or (
            trip.customer_order.customer if trip.customer_order_id else None
        )
        price = (
            DeliveryService.get_latest_selling_price(trip.product_id, customer.id)
            if customer is not None
            else None
        )
        return Response({"price": str(price) if price is not None else None})

    @action(detail=True, methods=["post"], url_path="delivery-control")
    def delivery_control(self, request, pk=None):
        """Confirm discharge/quantity control for this trip and finalize
        delivery (docs/PHASE_4_PLAN.md Etape 6): creates the DeliveryControl,
        the TransportDeduction (if any chargeable loss), the Sale and its
        DRAFT Invoice, and transitions the trip to DELIVERED - all inside
        DeliveryService.record_delivery()'s single atomic transaction.

        POST /api/trips/{id}/delivery-control/
        """
        trip = self.get_object()
        input_serializer = DeliveryControlRequestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            control = DeliveryService.record_delivery(
                trip_id=trip.id,
                received_qty=data["received_quantity"],
                control_date=data["control_date"],
                method=data["method"],
                controller=request.user,
                anomaly_confirmed_by=data.get("anomaly_confirmed_by"),
                document=data.get("document"),
                notes=data.get("notes", ""),
                unit_selling_price=data.get("unit_selling_price"),
                confirm_loss=data.get("confirm_loss", False),
            )
        except DeliveryAnomalyConfirmationRequired as exc:
            # Plan Section 1.D: reçu > chargé without an authorized
            # confirmation stops automatic validation - 422, not 400/500.
            return Response(
                {"detail": str(exc)},
                status=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except SaleBelowCostConfirmationRequired as exc:
            # Same "confirmation required, not a plain validation error"
            # class as the anomaly gate above - 422 lets the frontend show
            # the loss warning + checkbox instead of a generic form error.
            return Response(
                {"detail": str(exc)},
                status=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ValueError as exc:
            # Covers SellingPriceNotConfigured and InvalidTripTransition too
            # (both are ValueError subclasses) - anything else that stops
            # confirmation before the anomaly/below-cost gates is a plain 400.
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(
            DeliveryControlSerializer(control, context={"request": request}).data,
            status=http_status.HTTP_201_CREATED,
        )
