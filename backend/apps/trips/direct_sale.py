# Direct client attribution from Ventes (docs/superpowers/specs/2026-11-02-
# attribution-client-directe-design.md).
#
# One atomic operation links trips to a customer (registered or walk-in),
# treats them as arrived, parks the selling price on the trip and - when the
# received quantity is known - delivers, invoices and, for a walk-in, books the
# full cash payment. Everything reuses the existing services: this module only
# composes them.

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.customers.models import Customer
from apps.sales.models import Sale
from apps.trips.models import DeliveryControl, Trip
from apps.trips.services import (
    DeliveryService,
    TripCostService,
    TripWorkflowService,
)

# Same statuses the Ventes picker offers (SaleList.vue ASSIGNABLE_STATUSES).
ASSIGNABLE_STATUSES = {
    Trip.Status.CUSTOMS,
    Trip.Status.ARRIVED_AT_COMPANY_STOCK,
    Trip.Status.STOCKED,
}


def _validate_payment_destination(payment_destination):
    if not payment_destination or payment_destination.get("destination") not in ("BANK", "CASH"):
        raise ValueError(
            "Choisissez le compte (banque ou caisse) qui reçoit le paiement du client de passage."
        )


def _validate_quantity(trip, quantity):
    if quantity is None or quantity <= 0 or quantity > trip.quantity_loaded:
        raise ValueError(
            f"La quantité reçue du trajet {trip.reference} doit être comprise entre 0 "
            f"(exclu) et la quantité chargée ({trip.quantity_loaded} L)."
        )


class DirectSaleService:
    @staticmethod
    @transaction.atomic
    def assign_and_arrive(
        trip_ids,
        *,
        customer_id,
        walk_in_name,
        unit_selling_price: Decimal,
        received_quantities,
        payment_destination,
        confirm_loss: bool,
        actor,
    ) -> list:
        trip_ids = list(dict.fromkeys(trip_ids))
        received_quantities = received_quantities or {}
        walk_in_name = walk_in_name.strip() if walk_in_name is not None else None

        if not trip_ids:
            raise ValueError("Sélectionnez au moins un trajet.")
        if (customer_id is None) == (walk_in_name is None):
            raise ValueError("Choisissez soit un client enregistré, soit un client de passage.")
        if walk_in_name is not None and not walk_in_name:
            raise ValueError("Le nom du client de passage est obligatoire.")
        if unit_selling_price is None or unit_selling_price <= 0:
            raise ValueError("Le prix de vente unitaire doit être supérieur à zéro.")

        trips = list(Trip.objects.select_for_update().filter(pk__in=trip_ids).order_by("id"))
        if len(trips) != len(trip_ids):
            raise ValueError("Un ou plusieurs trajets sont introuvables.")
        for trip in trips:
            if trip.status not in ASSIGNABLE_STATUSES:
                raise ValueError(
                    f"Le trajet {trip.reference} ({trip.status}) ne peut pas être attribué à un client."
                )
            if hasattr(trip, "sale"):
                raise ValueError(f"Le trajet {trip.reference} a déjà une vente enregistrée.")
            if trip.id in received_quantities:
                _validate_quantity(trip, received_quantities[trip.id])
        if walk_in_name is not None and received_quantities:
            _validate_payment_destination(payment_destination)

        if walk_in_name is not None:
            customer = Customer.objects.create(name=walk_in_name, is_walk_in=True)
        else:
            customer = Customer.objects.get(pk=customer_id)

        TripCostService.assign_customers_group_for_sale(trip_ids, customer.id, actor)
        Trip.objects.filter(pk__in=trip_ids).update(
            pending_unit_selling_price=unit_selling_price, updated_at=timezone.now()
        )
        for trip_id in trip_ids:
            TripWorkflowService.transition_trip(trip_id, Trip.Status.ARRIVED_AT_CLIENT, actor)

        for trip_id in trip_ids:
            if trip_id in received_quantities:
                DirectSaleService.confirm_received_quantity(
                    trip_id,
                    received_quantities[trip_id],
                    payment_destination=payment_destination,
                    confirm_loss=confirm_loss,
                    actor=actor,
                )
        return list(Trip.objects.filter(pk__in=trip_ids).order_by("id"))

    @staticmethod
    @transaction.atomic
    def confirm_received_quantity(
        trip_id,
        received_quantity: Decimal,
        *,
        payment_destination,
        confirm_loss: bool,
        actor,
    ) -> Trip:
        trip = Trip.objects.select_for_update().get(pk=trip_id)
        if (
            trip.status != Trip.Status.ARRIVED_AT_CLIENT
            or trip.pending_unit_selling_price is None
            or hasattr(trip, "sale")
        ):
            raise ValueError(
                f"Le trajet {trip.reference} n'attend pas de quantité reçue."
            )
        _validate_quantity(trip, received_quantity)
        is_walk_in = trip.client.is_walk_in
        if is_walk_in:
            _validate_payment_destination(payment_destination)

        DeliveryService.record_delivery(
            trip.id,
            received_qty=received_quantity,
            control_date=timezone.localdate(),
            method=DeliveryControl.Method.MANUAL_GAUGE,
            controller=actor,
            unit_selling_price=trip.pending_unit_selling_price,
            confirm_loss=confirm_loss,
        )
        # The quantity typed here IS the client's final word: record it as the
        # client verification too, so the trip closes (COMPLETED) and its invoice
        # is validated right away - no second "Enregistrer la quantité reçue par
        # le client" step. The delivery already holds this quantity, so the
        # verification changes no amount; a later fix goes through the audited
        # "Corriger la vérification client".
        DeliveryService.record_client_verification(
            trip.id, received_quantity, timezone.localdate(), actor
        )
        Trip.objects.filter(pk=trip.id).update(
            pending_unit_selling_price=None, updated_at=timezone.now()
        )

        if is_walk_in:
            invoice = Sale.objects.get(trip_id=trip.id).billing_invoice
            if invoice is not None:
                DirectSaleService._record_full_cash_payment(
                    trip.client, invoice, payment_destination, actor
                )
        trip.refresh_from_db()
        return trip

    @staticmethod
    def _record_full_cash_payment(customer, invoice, payment_destination, actor):
        # Imported lazily (same circular-import reason as TripCancellationService).
        from apps.finance.serializers import CustomerPaymentSerializer
        from apps.sales.models import Invoice
        from apps.sales.services import InvoiceService

        # Paid at invoicing, so it must be payable: a DRAFT invoice is never
        # moved to PAID by an allocation (and stays editable under a
        # payment). Validate first, then the allocation settles it.
        if invoice.status == Invoice.Status.DRAFT:
            invoice = InvoiceService.validate_invoice(invoice.id, actor)
        destination = payment_destination["destination"]
        data = {
            "customer": customer.id,
            "amount": str(invoice.total_amount),
            "payment_date": timezone.localdate().isoformat(),
            "method": "BANK_TRANSFER" if destination == "BANK" else "CASH",
            "destination": destination,
            "bank_account": payment_destination.get("bank_account"),
            "cash_account": payment_destination.get("cash_account"),
            "allocations": [{"invoice": invoice.id, "amount": str(invoice.total_amount)}],
        }
        serializer = CustomerPaymentSerializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            raise ValueError(f"Paiement du client de passage invalide : {exc.detail}") from exc
        serializer.save(recorded_by=actor)
