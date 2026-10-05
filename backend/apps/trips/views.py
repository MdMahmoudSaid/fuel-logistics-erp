import re

from django.db import IntegrityError, transaction
from django.db.models import BigIntegerField, Max
from django.db.models.functions import Cast, Substr
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
    AssignCustomersRequestSerializer,
    ClientVerificationCorrectionRequestSerializer,
    ClientVerificationRequestSerializer,
    DeliveryControlRequestSerializer,
    DeliveryControlSerializer,
    TripSerializer,
    TripStatusHistorySerializer,
    prime_trip_list,
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

# Statuses that are the OUTCOME of a dedicated, data-collecting flow - never
# a plain status-bar transition. DELIVERED is produced only by the delivery
# control (POST /delivery-control/: captures the sale price, creates the
# Sale + DRAFT invoice); COMPLETED only by the client verification (POST
# /client-verification/: captures the received quantity / losses). Letting
# the raw status bar jump straight to either one skipped those steps and
# left a trip with no Sale - which then showed up wrongly as "en cours" on
# the dashboard (2026-09-07 recette). get_allowed_targets() itself is left
# untouched: DELIVERED/COMPLETED stay valid *workflow* transitions so the
# two services above can still reach them - this is a guard on the manual
# entry point only.
_FORM_ONLY_STATUSES = {Trip.Status.DELIVERED, Trip.Status.COMPLETED}

_FORM_ONLY_STATUS_DETAIL = {
    Trip.Status.DELIVERED: (
        "Le passage au statut « Livre » se fait uniquement via le controle "
        "de livraison : saisissez le prix de vente unitaire puis cliquez sur "
        "« Confirmer la livraison »."
    ),
    Trip.Status.COMPLETED: (
        "Le passage au statut « Termine » se fait uniquement via la "
        "verification client : saisissez la quantite recue / les pertes puis "
        "cliquez sur « Enregistrer la verification »."
    ),
}


def _generate_next_reference(truck) -> str:
    """Plate pair plus a sequence, fixed at creation for historical stability.

    Prefix matching uses escaped, normalized plates; numeric ordering keeps
    the sequence correct beyond 999999. The unique reference constraint and
    perform_create retries handle concurrent creates for the same plate pair.
    """
    def plate(value, fallback):
        return re.sub(r"[^\w-]+", "-", value.strip().upper()).strip("-") or fallback

    tractor = plate(truck.tractor_registration, "SANS-TRACTEUR")
    tanker = plate(truck.tanker_registration, "SANS-CITERNE")
    prefix = f"{_REFERENCE_PREFIX}{tractor}-{tanker}-"
    last_number = (
        Trip.objects.filter(
            reference__startswith=prefix,
            reference__regex=rf"^{re.escape(prefix)}[0-9]{{{_REFERENCE_WIDTH},18}}$",
        )
        .aggregate(number=Max(Cast(Substr("reference", len(prefix) + 1), BigIntegerField())))
        ["number"]
        or 0
    )
    return f"{prefix}{last_number + 1:0{_REFERENCE_WIDTH}d}"


class TripViewSet(viewsets.ModelViewSet):
    # Everything TripSerializer embeds is loaded here in bulk - one query
    # per related record per row made the trips page slow.
    queryset = Trip.objects.select_related(
        "supplier_order",
        "truck",
        "transporter",
        "driver",
        "supplier",
        "product",
        "client",
        "created_by__role",
        "cession_letter__created_by__role",
        "delivery_control__controller__role",
        "delivery_control__anomaly_confirmed_by__role",
    ).prefetch_related(
        "cession_letter__documents__uploaded_by",
        "verification_corrections__corrected_by__role",
    )
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

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        if page is not None:
            prime_trip_list(page)
        return page

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
            reference = _generate_next_reference(serializer.validated_data["truck"])
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

        if new_status in _FORM_ONLY_STATUSES:
            return Response(
                {"detail": _FORM_ONLY_STATUS_DETAIL[new_status]},
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

        data = TripSerializer(trip, context={"request": request}).data
        data["traversed_statuses"] = trip.traversed_statuses
        return Response(data)

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
        # Strip the form-only statuses: they're valid workflow targets (the
        # delivery-control / client-verification services still transition
        # into them) but must never be offered as a manual status-bar choice.
        allowed = TripWorkflowService.get_allowed_targets(trip) - _FORM_ONLY_STATUSES
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

    @action(detail=False, methods=["post"], url_path="assign-customers")
    def assign_customers(self, request):
        """Assign one customer to several trips billed on a single invoice.

        POST /api/trips/assign-customers/  body: {customer, trips: [ids]}
        """
        input_serializer = AssignCustomersRequestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            trips = TripCostService.assign_customers_group_for_sale(
                data["trips"], data["customer"].id, request.user
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST
            )
        return Response(
            TripSerializer(trips, many=True, context={"request": request}).data
        )

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
                received_qty=data.get("received_quantity"),
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

    @action(detail=True, methods=["post"], url_path="client-verification")
    def client_verification(self, request, pk=None):
        """Post-delivery client quantity check (client modifications
        2026-09-04) - see DeliveryService.record_client_verification().

        POST /api/trips/{id}/client-verification/
        """
        trip = self.get_object()
        input_serializer = ClientVerificationRequestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            control = DeliveryService.record_client_verification(
                trip_id=trip.id,
                received_qty=data["received_quantity"],
                verified_at=data["verified_at"],
                actor=request.user,
                notes=data.get("notes", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(DeliveryControlSerializer(control, context={"request": request}).data)

    @action(
        detail=True, methods=["post"], url_path="correct-client-verification"
    )
    def correct_client_verification(self, request, pk=None):
        """Audited correction of an already-recorded client verification
        (feedback 2026-09-10) - see
        DeliveryService.correct_client_verification().

        POST /api/trips/{id}/correct-client-verification/
        """
        trip = self.get_object()
        input_serializer = ClientVerificationCorrectionRequestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            control = DeliveryService.correct_client_verification(
                trip_id=trip.id,
                received_qty=data["received_quantity"],
                reason=data["reason"],
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(DeliveryControlSerializer(control, context={"request": request}).data)
