from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission

from .models import Driver, Transporter, Truck
from .serializers import DriverSerializer, TransporterSerializer, TruckSerializer

_TRUCK_ID_PREFIX = "TRK-"
_TRUCK_ID_WIDTH = 4
_MAX_TRUCK_ID_ATTEMPTS = 5


def _generate_next_truck_internal_id() -> str:
    """Sequential, zero-padded internal id (TRK-0001, TRK-0002, ...) - same
    regex-scoped/retry approach as apps.trips.views._generate_next_reference,
    used only when the user leaves the field blank on creation."""
    last = (
        Truck.objects.filter(internal_id__regex=rf"^{_TRUCK_ID_PREFIX}\d{{{_TRUCK_ID_WIDTH}}}$")
        .order_by("-internal_id")
        .first()
    )
    last_number = 0
    if last:
        try:
            last_number = int(last.internal_id.removeprefix(_TRUCK_ID_PREFIX))
        except ValueError:
            last_number = 0
    return f"{_TRUCK_ID_PREFIX}{last_number + 1:0{_TRUCK_ID_WIDTH}d}"


class TransporterViewSet(viewsets.ModelViewSet):
    queryset = Transporter.objects.all()
    serializer_class = TransporterSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "operations"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("available") == "true":
            # Imported lazily: apps.transport sits below apps.trips in the
            # app dependency graph (same convention as the `trips` action
            # below).
            from apps.trips.services import TransporterAvailabilityService

            available_ids = TransporterAvailabilityService.get_available_transporters()
            queryset = queryset.filter(pk__in=available_ids)
        return queryset

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Transporter settlement breakdown: gross fees earned, loss
        deductions, advances consumed and what's already been paid
        (docs/PHASE_5_PLAN.md Etape 8; guide Section 1.5/8.6: "earned -
        deductions - advances - payments = transporter outstanding").

        GET /api/transporters/{id}/ledger/
        """
        # Imported lazily: apps.transport sits below apps.finance in the app
        # dependency graph (apps.finance.models references
        # "transport.Transporter" only via string FK).
        from apps.finance.models import TransportPayment
        from apps.finance.serializers import (
            TransporterAdvanceSerializer,
            TransportPaymentSerializer,
        )

        transporter = self.get_object()
        payments = TransportPayment.objects.filter(transporter=transporter).select_related(
            "trip", "advance_applied"
        )
        advances = transporter.advances.all()

        gross_amount = sum((p.base_amount for p in payments), Decimal("0.00"))
        deductions = sum((p.deduction_amount for p in payments), Decimal("0.00"))
        advances_applied = sum(
            (p.advance_applied.amount for p in payments if p.advance_applied_id),
            Decimal("0.00"),
        )
        net_amount = sum((p.net_amount for p in payments), Decimal("0.00"))
        settled = sum(
            (p.net_amount for p in payments if p.status == TransportPayment.Status.PAID),
            Decimal("0.00"),
        )
        unsettled_advances = sum(
            (a.amount for a in advances if not a.settled), Decimal("0.00")
        )

        return Response(
            {
                "transporter": TransporterSerializer(transporter).data,
                "gross_amount": f"{gross_amount:.2f}",
                "deductions": f"{deductions:.2f}",
                "advances_applied": f"{advances_applied:.2f}",
                "settled": f"{settled:.2f}",
                "net_outstanding": f"{net_amount - settled:.2f}",
                "unsettled_advances": f"{unsettled_advances:.2f}",
                "payments": TransportPaymentSerializer(
                    payments, many=True, context={"request": request}
                ).data,
                "advances": TransporterAdvanceSerializer(
                    advances, many=True, context={"request": request}
                ).data,
            }
        )


class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer
    permission_classes = [HasModulePermission]
    module = "operations"


class TruckViewSet(viewsets.ModelViewSet):
    queryset = Truck.objects.all()
    serializer_class = TruckSerializer
    filterset_fields = ["status", "ownership_type"]
    permission_classes = [HasModulePermission]
    module = "operations"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("available") == "true":
            # Imported lazily: apps.transport sits below apps.trips in the
            # app dependency graph. Trip.status is the actual source of
            # truth for availability - the stored Truck.status field is
            # never written back to ON_TRIP anywhere, so filtering on it
            # directly would silently include occupied trucks.
            from apps.trips.services import TruckAvailabilityService

            queryset = queryset.filter(
                pk__in=TruckAvailabilityService.get_available_trucks()
            )
        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        if serializer.validated_data.get("internal_id"):
            serializer.save()
            return
        for _ in range(_MAX_TRUCK_ID_ATTEMPTS):
            try:
                with transaction.atomic():
                    serializer.save(internal_id=_generate_next_truck_internal_id())
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer un identifiant interne de camion unique "
            f"apres {_MAX_TRUCK_ID_ATTEMPTS} tentatives."
        )

    @action(detail=True, methods=["get"])
    def trips(self, request, pk=None):
        """Full trip history for this physical truck (newest first).

        GET /api/trucks/{id}/trips/
        """
        # Imported lazily: transport sits below trips in the app dependency
        # graph (Trip.truck points here, not the reverse).
        from apps.trips.serializers import TripSerializer

        truck = self.get_object()
        trips = truck.trips.all()
        return Response(
            TripSerializer(trips, many=True, context={"request": request}).data
        )
