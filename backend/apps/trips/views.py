from django.db import IntegrityError, transaction
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import Trip
from .serializers import (
    DeliveryControlRequestSerializer,
    DeliveryControlSerializer,
    TripSerializer,
    TripStatusHistorySerializer,
)
from .services import (
    DeliveryAnomalyConfirmationRequired,
    DeliveryService,
    InvalidTripTransition,
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
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = _generate_next_reference()
            try:
                with transaction.atomic():
                    serializer.save(reference=reference, created_by=self.request.user)
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
            )
        except DeliveryAnomalyConfirmationRequired as exc:
            # Plan Section 1.D: reçu > chargé without an authorized
            # confirmation stops automatic validation - 422, not 400/500.
            return Response(
                {"detail": str(exc)},
                status=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ValueError as exc:
            # Covers SellingPriceNotConfigured and InvalidTripTransition too
            # (both are ValueError subclasses) - anything else that stops
            # confirmation before the anomaly gate is a plain 400.
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(
            DeliveryControlSerializer(control, context={"request": request}).data,
            status=http_status.HTTP_201_CREATED,
        )
