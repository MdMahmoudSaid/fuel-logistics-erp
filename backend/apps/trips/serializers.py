import logging
from decimal import Decimal

from django.db.models import Count, Sum
from rest_framework import serializers

from apps.accounts.models import Role, User
from apps.accounts.serializers import UserSerializer
from apps.core.request_cache import memoize_per_request
from apps.core.serializers import ProductSerializer
from apps.customers.models import Customer
from apps.customers.serializers import CustomerBriefSerializer
from apps.documents.models import Document
from apps.purchasing.serializers import CessionLetterSerializer
from apps.purchasing.services import SupplierStockService
from apps.suppliers.serializers import SupplierBriefSerializer
from apps.transport.serializers import DriverSerializer, TransporterBriefSerializer, TruckSerializer
from apps.trips.models import (
    ClientVerificationCorrection,
    DeliveryControl,
    Trip,
    TripStatusHistory,
)
from apps.trips.services import TripCostService, TruckAvailabilityService

# Dedicated logger for the force-override audit trail (docs/PHASE_3_PLAN.md
# Etape 5: "Si force, generer un log d'audit"). apps.audit has no AuditLog
# model yet - that table is Phase 6 scope (roadmap/phase_6_management.md,
# guide §9.9) - so this is a structured log line today, migrated to a real
# AuditLog row once that model exists rather than inventing it early.
audit_logger = logging.getLogger("apps.trips.audit")


class TripStatusHistorySerializer(serializers.ModelSerializer):
    """Read-only: history rows are written exclusively by
    TripWorkflowService.transition_trip() and are immutable at the model
    level (Trip.save()/.delete() both raise past creation)."""

    changed_by_detail = UserSerializer(source="changed_by", read_only=True)

    class Meta:
        model = TripStatusHistory
        fields = [
            "id",
            "trip",
            "previous_status",
            "new_status",
            "changed_by",
            "changed_by_detail",
            "changed_at",
            "notes",
        ]
        read_only_fields = fields


@memoize_per_request
def _truck_load_count(truck_id, cession_letter_id) -> int:
    return (
        Trip.objects.filter(truck_id=truck_id, cession_letter_id=cession_letter_id)
        .exclude(status=Trip.Status.CANCELLED)
        .count()
    )


def prime_trip_list(trips) -> None:
    """Pre-compute, in a handful of queries, the per-trip figures
    TripSerializer would otherwise query row by row (cost basis, cession
    letter remaining quantity, truck load count) for one list page."""
    trips = list(trips)
    TripCostService.prime_cost_bases(trips)
    cession_ids = {trip.cession_letter_id for trip in trips if trip.cession_letter_id}
    if not cession_ids:
        return
    active = Trip.objects.filter(cession_letter_id__in=cession_ids).exclude(
        status=Trip.Status.CANCELLED
    )
    loaded = dict(
        active.values("cession_letter_id")
        .annotate(total=Sum("quantity_loaded"))
        .values_list("cession_letter_id", "total")
    )
    counts = {
        (row["truck_id"], row["cession_letter_id"]): row["count"]
        for row in active.values("truck_id", "cession_letter_id").annotate(count=Count("id"))
    }
    for trip in trips:
        cession = trip.cession_letter
        if cession is None:
            continue
        SupplierStockService.get_cession_remaining.prime(
            cession.authorized_quantity - (loaded.get(cession.id) or Decimal("0.00")), cession
        )
        _truck_load_count.prime(
            counts.get((trip.truck_id, cession.id), 0), trip.truck_id, cession.id
        )


class TripSerializer(serializers.ModelSerializer):
    truck_detail =TruckSerializer(source="truck", read_only=True)
    transporter_detail = TransporterBriefSerializer(source="transporter", read_only=True)
    driver_detail = DriverSerializer(source="driver", read_only=True)
    supplier_detail = SupplierBriefSerializer(source="supplier", read_only=True)
    product_detail = ProductSerializer(source="product", read_only=True)
    client_detail = CustomerBriefSerializer(source="client", read_only=True)
    created_by_detail = UserSerializer(source="created_by", read_only=True)
    cession_letter_detail = CessionLetterSerializer(source="cession_letter", read_only=True)
    cession_letter_truck_load_count = serializers.SerializerMethodField()
    # Prix de revient / L (client request 2026-09-25): starts at the
    # supplier's purchase price and grows as transport commission and trip
    # expenses are added - computed live, never stored.
    unit_cost = serializers.SerializerMethodField()
    # Feedback (2026-09-10): the client-verification correction workflow
    # needs the DeliveryControl's authoritative current received_quantity
    # and its audit trail (verification_corrections) - the frontend's
    # loss-report reuse (see its own comment in TripDetail.vue) is a report
    # snapshot that never refreshes after a correction and carries no
    # correction history, so it can't drive that workflow. Unlike the
    # report-reuse decision, this is a real, ongoing need, not "just one
    # display" - hence the nested field this time.
    delivery_control_detail = serializers.SerializerMethodField()
    # Not a model field: lets an Admin bypass the active-truck lock (plan
    # §1.D). Always popped out of validated_data in validate() below.
    force = serializers.BooleanField(write_only=True, required=False, default=False)
    # Optional: TripViewSet.perform_create generates BL-YYYYMM-NNNN when left
    # blank, unlike the always-server-generated references in apps.purchasing
    # (user may have a real paper BL number to record).
    bl_reference = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Trip
        fields = [
            "id",
            "reference",
            "truck",
            "truck_detail",
            "transporter",
            "transporter_detail",
            "driver",
            "driver_detail",
            "supplier",
            "supplier_detail",
            "supplier_order",
            "cession_letter",
            "cession_letter_detail",
            "cession_letter_truck_load_count",
            "unit_cost",
            "delivery_control_detail",
            "product",
            "product_detail",
            "quantity_loaded",
            "client",
            "client_detail",
            "customer_order",
            "destination_type",
            "loading_date",
            "bl_reference",
            "status",
            "notes",
            "created_by",
            "created_by_detail",
            "force",
            "created_at",
            "updated_at",
        ]
        # reference is generated by the view (Etape 6); status only ever
        # moves through TripWorkflowService (guide §6.8), never a direct
        # write here.
        read_only_fields = [
            "id",
            "reference",
            "status",
            # Server-computed from client/customer_order presence (see
            # _normalize_destination_type below), never taken from client
            # input directly.
            "destination_type",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        force = data.pop("force", False)

        self._validate_cession_quantity(data)
        self._validate_truck_capacity(data)
        self._validate_truck_availability(data, force)
        self._validate_and_derive_transporter(data)
        self._validate_client_customer_order_consistency(data)
        self._normalize_destination_type(data)

        return data

    def get_unit_cost(self, obj) -> str:
        unit_cost = TripCostService.calculate_trip_cost_basis(obj)["unit_cost"]
        return f"{unit_cost:.4f}"

    def get_cession_letter_truck_load_count(self, obj) -> int:
        """How many times this trip's truck has been loaded under this
        exact cession letter (added client request 2026-09-10: "Trajets &
        chargements" needs to show, per trip, which cession letter it was
        loaded from and how many times that truck has loaded against it).
        Counts the trip itself, so a truck's first load under a cession
        letter reads 1, not 0. Cancelled trips never really happened, so
        they're excluded, same as every other loaded-quantity aggregate in
        this codebase (SupplierStockService.get_purchase_loaded_quantity)."""
        return _truck_load_count(obj.truck_id, obj.cession_letter_id)

    def get_delivery_control_detail(self, obj) -> dict | None:
        try:
            control = obj.delivery_control
        except DeliveryControl.DoesNotExist:
            return None
        return DeliveryControlSerializer(control, context=self.context).data

    def _resolve(self, data, field):
        """`data[field]` if the caller touched it this request, else the
        current value on `self.instance` (None for a create). Distinct from
        the `data.get(x) or instance.x` pattern used by the checks above:
        those fields are never legitimately cleared to None/blank, but
        `client`/`customer_order` explicitly can be (moving a trip back to
        COMPANY_STOCK), so falling back on a falsy-but-provided value here
        would silently ignore that clear."""
        if field in data:
            return data[field]
        return getattr(self.instance, field, None)

    def _validate_client_customer_order_consistency(self, data):
        client = self._resolve(data, "client")
        customer_order = self._resolve(data, "customer_order")
        if client and customer_order and customer_order.customer_id != client.id:
            raise serializers.ValidationError(
                {
                    "client": (
                        "Le client direct ne correspond pas au client de la "
                        "commande client associee a ce trajet."
                    )
                }
            )

    def _normalize_destination_type(self, data):
        """Plan Section (Global Constraints): destination_type is derived,
        never independently settable - CUSTOMER whenever either a direct
        client or a customer order is attached, COMPANY_STOCK otherwise
        (the "Stock de l'entreprise" first-class state)."""
        client = self._resolve(data, "client")
        customer_order = self._resolve(data, "customer_order")
        data["destination_type"] = (
            Trip.DestinationType.CUSTOMER
            if (client or customer_order)
            else Trip.DestinationType.COMPANY_STOCK
        )

    def _validate_cession_quantity(self, data):
        cession_letter = data.get("cession_letter") or (
            self.instance.cession_letter if self.instance else None
        )
        quantity_loaded = data.get("quantity_loaded")
        if quantity_loaded is None and self.instance:
            quantity_loaded = self.instance.quantity_loaded

        if not cession_letter or quantity_loaded is None:
            return

        try:
            # Locks the CessionLetter row inside the surrounding atomic
            # request (guide §5.4 / §15 concurrency rule).
            SupplierStockService.validate_and_lock_cession_quantity(
                cession_id=cession_letter.id,
                requested_qty=quantity_loaded,
                exclude_trip_id=self.instance.id if self.instance else None,
            )
        except ValueError as exc:
            raise serializers.ValidationError({"quantity_loaded": str(exc)})

    def _validate_truck_capacity(self, data):
        truck = data.get("truck") or (self.instance.truck if self.instance else None)
        quantity_loaded = data.get("quantity_loaded")
        if quantity_loaded is None and self.instance:
            quantity_loaded = self.instance.quantity_loaded

        if truck is None or quantity_loaded is None:
            return

        if quantity_loaded > truck.capacity_litres:
            raise serializers.ValidationError(
                {
                    "quantity_loaded": (
                        f"La quantite chargee ({quantity_loaded} L) ne peut pas "
                        f"depasser la capacite maximale du camion ({truck.capacity_litres} L)."
                    )
                }
            )

    def _validate_truck_availability(self, data, force):
        truck = data.get("truck") or (self.instance.truck if self.instance else None)
        if truck is None:
            return

        is_new_assignment = self.instance is None
        is_reassignment = self.instance is not None and truck.id != self.instance.truck_id
        if not (is_new_assignment or is_reassignment):
            return

        if TruckAvailabilityService.is_truck_available(truck.id):
            return

        request = self.context.get("request")
        user = getattr(request, "user", None)
        is_admin = bool(
            user
            and (user.is_superuser or (user.role and user.role.name == Role.NAME_ADMIN))
        )

        if not (force and is_admin):
            raise serializers.ValidationError(
                {
                    "truck": (
                        "Ce camion a deja un trajet actif. Reessayez avec "
                        "force=true (reserve aux administrateurs)."
                    )
                }
            )

        active_trip = TruckAvailabilityService.get_active_trip(truck.id)
        audit_logger.warning(
            "TRUCK_FORCE_OVERRIDE truck=%s active_trip=%s actor=%s",
            truck.internal_id,
            active_trip.reference if active_trip else None,
            user.email,
        )


    def _validate_and_derive_transporter(self, data):
        """Bug fix (2026-09-03 recette manuelle): truck.owner_transporter
        is now mandatory in every case (TruckSerializer.validate() - a real
        transporter for EXTERNAL, the seeded internal one for
        COMPANY_OWNED), so a Trip's transporter is always simply derived
        from its truck - auto-filled if the caller didn't send one,
        rejected if it sent a mismatching one (readonly on the frontend,
        but the backend never trusts that alone). Replaces Phase 6's
        original ownership_type branching, which forced transporter=None
        for a company-owned truck.
        """
        truck = data.get("truck") or (self.instance.truck if self.instance else None)
        if truck is None:
            return

        submitted = data.get("transporter") if "transporter" in data else None
        if submitted is not None and submitted.id != truck.owner_transporter_id:
            raise serializers.ValidationError(
                {
                    "transporter": (
                        "Le transporteur doit correspondre au transporteur du camion "
                        "selectionne."
                    )
                }
            )
        data["transporter"] = truck.owner_transporter


class ClientVerificationCorrectionSerializer(serializers.ModelSerializer):
    """Read-only audit trail entry - always written by
    DeliveryService.correct_client_verification(), never directly through
    the API. Mirrors apps.sales.serializers.InvoiceCorrectionSerializer."""

    corrected_by_detail = UserSerializer(source="corrected_by", read_only=True)

    class Meta:
        model = ClientVerificationCorrection
        fields = [
            "id",
            "previous_received_quantity",
            "new_received_quantity",
            "corrected_by",
            "corrected_by_detail",
            "corrected_at",
            "reason",
        ]
        read_only_fields = fields


class DeliveryControlSerializer(serializers.ModelSerializer):
    """Read-only representation of a confirmed DeliveryControl
    (docs/PHASE_4_PLAN.md Etape 6). Entirely produced by
    DeliveryService.record_delivery() via TripViewSet.delivery_control() -
    see DeliveryControlRequestSerializer below for the write path."""

    controller_detail = UserSerializer(source="controller", read_only=True)
    anomaly_confirmed_by_detail = UserSerializer(
        source="anomaly_confirmed_by", read_only=True
    )
    verification_corrections = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryControl
        fields = [
            "id",
            "trip",
            "loaded_quantity",
            "received_quantity",
            "loss_quantity",
            "chargeable_loss_quantity",
            "tolerance_quantity",
            "control_date",
            "controller",
            "controller_detail",
            "method",
            "document",
            "notes",
            "verified_at",
            "anomaly_confirmed_by",
            "anomaly_confirmed_by_detail",
            "anomaly_confirmed_at",
            "verification_corrections",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_verification_corrections(self, obj) -> list[dict]:
        return ClientVerificationCorrectionSerializer(
            obj.trip.verification_corrections.all(), many=True
        ).data


class DeliveryControlRequestSerializer(serializers.Serializer):
    """Input validation for POST /api/trips/{id}/delivery-control/.

    Not a ModelSerializer: the actual DeliveryControl (plus its
    TransportDeduction/Sale/Invoice side effects) is created exclusively by
    DeliveryService.record_delivery() under a Trip row lock (guide Section
    13/15) - this only validates and type-converts the request body before
    the view hands it to that service.

    The reçu > chargé anomaly gate itself is intentionally NOT re-checked
    here: DeliveryService already raises DeliveryAnomalyConfirmationRequired
    for it, and duplicating that rule here would risk the two drifting
    apart (guide Section 5.5 - never duplicate a formula/rule across
    serializers and services).
    """

    received_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0"),
        required=False, allow_null=True,
    )
    control_date = serializers.DateField()
    method = serializers.ChoiceField(choices=DeliveryControl.Method.choices)
    anomaly_confirmed_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    document = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all(), required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    unit_selling_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
    )
    # Client modifications Task 3: explicit acknowledgement that this Sale's
    # unit_selling_price is below the trip's unit cost
    # (TripCostService.calculate_trip_cost_basis) - the below-cost check
    # itself lives solely in DeliveryService.record_delivery
    # (SaleBelowCostConfirmationRequired), same "don't duplicate a rule
    # across serializer and service" convention as the anomaly gate above.
    confirm_loss = serializers.BooleanField(required=False, default=False)


class ClientVerificationRequestSerializer(serializers.Serializer):
    """Input validation for POST /api/trips/{id}/client-verification/.

    Not a ModelSerializer: the actual DeliveryControl update (plus the
    TransportDeduction re-sync) is owned exclusively by
    DeliveryService.record_client_verification() under a Trip row lock
    (same convention as DeliveryControlRequestSerializer above) - this
    only validates and type-converts the request body before the view
    hands it to that service.
    """

    received_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0")
    )
    verified_at = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ClientVerificationCorrectionRequestSerializer(serializers.Serializer):
    """Input validation for POST /api/trips/{id}/correct-client-verification/.

    Not a ModelSerializer, same convention as ClientVerificationRequestSerializer
    above - the actual mutation is owned exclusively by
    DeliveryService.correct_client_verification(). `reason` is required
    (unlike the first verification): this is an audited correction, not a
    routine data entry.
    """

    received_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0")
    )
    reason = serializers.CharField()


class AssignCustomerRequestSerializer(serializers.Serializer):
    """Input validation for POST /api/trips/{id}/assign-customer/.

    Not a ModelSerializer: the actual mutation (plus its "reject once a
    Sale exists" rule) is owned exclusively by
    TripCostService.assign_customer_for_sale() under a Trip row lock (same
    convention as DeliveryControlRequestSerializer above) - this only
    validates the customer id before the view hands it to that service.
    """

    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())


class AssignCustomersRequestSerializer(serializers.Serializer):
    """Input for POST /api/trips/assign-customers/ (several trips, one
    customer, one invoice)."""

    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    trips = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False
    )
