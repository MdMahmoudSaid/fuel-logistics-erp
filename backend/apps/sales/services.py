# Derived CustomerOrder aggregates and status projection (docs/PHASE_3_PLAN.md
# Etape 4 "Mettre a jour dynamiquement le statut de la commande client
# associee" + ERP_Implementation_Experience_Guide.md Section 6.4 / Section 5.5).
#
# assigned/loaded/delivered/remaining quantities are never stored on
# CustomerOrder - they are always computed from the order's Trip rows so
# cancellations and corrections can never cause drift (guide Section 5.1).
# status is likewise never set directly past CONFIRMED:
# TripWorkflowService.transition_trip() calls recompute_status() after every
# trip status change that touches an order.

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.sales.models import CustomerOrder, Invoice, InvoiceCorrection

ZERO = Decimal("0.00")

# Trip statuses reached once the truck has physically loaded product for
# this order (LOADED onward). BLOCKED/CANCELLED are intentionally excluded.
_LOADED_ONWARD_STATUSES = {
    "LOADED",
    "IN_TRANSIT",
    "BORDER",
    "CUSTOMS",
    "ARRIVED_AT_CLIENT",
    "QUANTITY_CONTROL",
    "DELIVERED",
    "COMPLETED",
}
_DELIVERED_STATUSES = {"DELIVERED", "COMPLETED"}

# Statuses recompute_status() is allowed to move an order between. DRAFT
# (not yet confirmed), CLOSED and CANCELLED are manual lifecycle boundaries
# set by a user action, not by trip aggregation, so they're left untouched.
_AUTO_MANAGED_STATUSES = {
    CustomerOrder.Status.CONFIRMED,
    CustomerOrder.Status.PARTIALLY_ASSIGNED,
    CustomerOrder.Status.IN_PROGRESS,
    CustomerOrder.Status.PARTIALLY_DELIVERED,
    CustomerOrder.Status.DELIVERED,
}


class CustomerOrderService:
    @staticmethod
    def get_assigned_quantity(order: CustomerOrder) -> Decimal:
        """Portion of the order already committed to a truck: the sum of
        quantity_loaded for every non-cancelled trip against this order."""
        return order.trips.exclude(status="CANCELLED").aggregate(
            total=Sum("quantity_loaded")
        )["total"] or ZERO

    @staticmethod
    def get_loaded_quantity(order: CustomerOrder) -> Decimal:
        return order.trips.filter(
            status__in=_LOADED_ONWARD_STATUSES
        ).aggregate(total=Sum("quantity_loaded"))["total"] or ZERO

    @staticmethod
    def get_delivered_quantity(order: CustomerOrder) -> Decimal:
        return order.trips.filter(
            status__in=_DELIVERED_STATUSES
        ).aggregate(total=Sum("quantity_loaded"))["total"] or ZERO

    @staticmethod
    def get_remaining_quantity(order: CustomerOrder) -> Decimal:
        return order.quantity_ordered - CustomerOrderService.get_delivered_quantity(
            order
        )

    @staticmethod
    def recompute_status(order: CustomerOrder) -> CustomerOrder:
        """Derive `order.status` from its trips' current state and persist
        it if it changed. No-op for DRAFT/CLOSED/CANCELLED orders (guide
        roadmap: "Status transitions ... derived by a service function, not
        set manually by users" - but only within the auto-managed range)."""
        if order.status not in _AUTO_MANAGED_STATUSES:
            return order

        assigned = CustomerOrderService.get_assigned_quantity(order)
        delivered = CustomerOrderService.get_delivered_quantity(order)

        if delivered >= order.quantity_ordered:
            target = CustomerOrder.Status.DELIVERED
        elif delivered > ZERO:
            target = CustomerOrder.Status.PARTIALLY_DELIVERED
        elif assigned >= order.quantity_ordered:
            target = CustomerOrder.Status.IN_PROGRESS
        elif assigned > ZERO:
            target = CustomerOrder.Status.PARTIALLY_ASSIGNED
        else:
            target = CustomerOrder.Status.CONFIRMED

        if target != order.status:
            order.status = target
            order.save(update_fields=["status", "updated_at"])
        return order


class InvoiceValidationError(ValueError):
    """Raised when validate_invoice() is called on an invoice that isn't
    DRAFT (e.g. already validated)."""


class InvoiceNotValidated(ValueError):
    """Raised when correct_invoice() is called on an invoice that hasn't
    been validated yet - a DRAFT invoice's fields should just be edited
    directly instead of going through the audited correction workflow
    (docs/PHASE_4_PLAN.md Section 1.E)."""


class UnsupportedCorrectionField(ValueError):
    """Raised when correct_invoice() is asked to correct a field it doesn't
    know how to apply/recompute."""


class InvoicePaidCorrectionUnsupported(ValueError):
    """Raised when a delivered-quantity adjustment is attempted on an
    invoice that is already (partially) paid or cancelled - reducing it
    would create a customer overpayment/credit, which has no automated
    handling yet (spec 2026-09-07). The operator must resolve the payment
    situation manually first."""


def _reject_non_billable_quantity(qty: Decimal, invoice_number: str) -> None:
    """Guard against a delivered quantity that `Sale`'s
    `CheckConstraint(delivered_quantity__gt=0)` would reject at the DB level
    (an IntegrityError, which the viewsets' `except ValueError` would miss ->
    HTTP 500). A total-loss client verification (received_quantity = 0) must
    be handled by cancelling the invoice / trip, not by billing a zero."""
    if qty <= 0:
        raise ValueError(
            f"Une quantité livrée nulle ou négative ne peut pas être facturée "
            f"(facture {invoice_number}) ; annulez plutôt la facture / le trajet."
        )


class InvoiceService:
    """Owns Invoice validation and post-validation corrections
    (docs/PHASE_4_PLAN.md Etape 5;
    ERP_Implementation_Experience_Guide.md Section 7.9/Section 21: "do not
    silently rewrite quantity/price - record correction/reversal with
    reason and actor").
    """

    @staticmethod
    @transaction.atomic
    def validate_invoice(invoice_id, actor) -> Invoice:
        """Freeze `invoice_id`'s operational amounts by moving it to
        VALIDATED. Past this point, only correct_invoice() may touch its
        financial data."""
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

        if invoice.status != Invoice.Status.DRAFT:
            raise InvoiceValidationError(
                f"Invoice {invoice.invoice_number} is already "
                f"{invoice.status} and cannot be validated again."
            )

        invoice.status = Invoice.Status.VALIDATED
        invoice.save(update_fields=["status", "updated_at"])
        return invoice

    @staticmethod
    @transaction.atomic
    def update_draft_pricing(invoice_id, unit_selling_price) -> Invoice:
        """Change a DRAFT invoice's initial selling price and recompute its
        total (feedback 2026-09-10: the initial price set on the trip's
        delivery control is sometimes wrong and needs fixing before the
        invoice is ever validated). Same "DRAFT -> Sale + Invoice edited
        directly, no audit row" convention as adjust_delivered_quantity()
        above and the InvoiceSerializer.validate() docstring - a DRAFT
        invoice's data was never frozen, so this is a plain edit, not an
        audited correction (that's correct_invoice(field="unit_selling_
        price"), VALIDATED-only)."""
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

        if invoice.status != Invoice.Status.DRAFT:
            raise ValueError(
                f"Invoice {invoice.invoice_number} is {invoice.status} ; "
                "only a DRAFT invoice's price can be edited directly - use "
                "the audited correction instead."
            )

        sale = invoice.sale
        sale.unit_selling_price = Decimal(str(unit_selling_price))
        sale.save()  # recomputes subtotal via Sale.save()
        invoice.total_amount = sale.subtotal
        invoice.save(update_fields=["total_amount", "updated_at"])
        return invoice

    @staticmethod
    @transaction.atomic
    def correct_invoice(invoice_id, field, new_value, reason, actor) -> Invoice:
        """Adjust a validated invoice's financial data under audit
        (docs/PHASE_4_PLAN.md Section 1.E). Only usable once VALIDATED - a
        DRAFT invoice's serializer should accept direct field edits instead,
        with no correction trail needed for data that was never frozen."""
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

        if invoice.status != Invoice.Status.VALIDATED:
            raise InvoiceNotValidated(
                f"Invoice {invoice.invoice_number} must be VALIDATED before "
                "it can be corrected; edit it directly while it is DRAFT."
            )

        sale = invoice.sale

        if field == "unit_selling_price":
            previous_value = str(sale.unit_selling_price)
            sale.unit_selling_price = Decimal(str(new_value))
            sale.save()  # recomputes subtotal via Sale.save()
            invoice.total_amount = sale.subtotal
            invoice.save(update_fields=["total_amount", "updated_at"])
        elif field == "delivered_quantity":
            _reject_non_billable_quantity(Decimal(str(new_value)), invoice.invoice_number)
            previous_value = str(sale.delivered_quantity)
            sale.delivered_quantity = Decimal(str(new_value))
            sale.save()  # recomputes subtotal via Sale.save()
            invoice.total_amount = sale.subtotal
            invoice.save(update_fields=["total_amount", "updated_at"])
        elif field == "total_amount":
            previous_value = str(invoice.total_amount)
            invoice.total_amount = Decimal(str(new_value))
            invoice.save(update_fields=["total_amount", "updated_at"])
        else:
            raise UnsupportedCorrectionField(
                f"'{field}' is not a correctable invoice field."
            )

        InvoiceCorrection.objects.create(
            invoice=invoice,
            field_name=field,
            previous_value=previous_value,
            new_value=str(new_value),
            corrected_by=actor,
            reason=reason,
        )
        return invoice

    @staticmethod
    @transaction.atomic
    def adjust_delivered_quantity(invoice_id, new_quantity, *, reason, actor) -> Invoice:
        """Set an invoice's billed quantity to `new_quantity` (the quantity
        the client actually received - spec 2026-09-07). This is the
        automated owner of a post-creation Sale.delivered_quantity mutation;
        `correct_invoice(field="delivered_quantity")` is the manual,
        VALIDATED-only equivalent.

        DRAFT      -> Sale + Invoice edited directly, no audit row.
        VALIDATED  -> same, plus an InvoiceCorrection row.
        (PARTIALLY_)PAID / CANCELLED -> InvoicePaidCorrectionUnsupported.
        No-op if new_quantity already equals the current delivered_quantity.
        """
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        sale = invoice.sale
        new_quantity = Decimal(str(new_quantity))
        _reject_non_billable_quantity(new_quantity, invoice.invoice_number)

        # no-op next: a call that changes nothing needs no guard, even on a
        # paid/cancelled invoice.
        if new_quantity == sale.delivered_quantity:
            return invoice

        if invoice.status in (
            Invoice.Status.PARTIALLY_PAID,
            Invoice.Status.PAID,
            Invoice.Status.CANCELLED,
        ):
            raise InvoicePaidCorrectionUnsupported(
                f"La facture {invoice.invoice_number} est {invoice.status} ; "
                "la correction de la quantité d'une facture encaissée ou "
                "annulée n'est pas prise en charge automatiquement."
            )

        previous_value = str(sale.delivered_quantity)
        sale.delivered_quantity = new_quantity
        sale.save()  # recomputes subtotal via Sale.save()
        invoice.total_amount = sale.subtotal
        invoice.save(update_fields=["total_amount", "updated_at"])

        if invoice.status == Invoice.Status.VALIDATED:
            InvoiceCorrection.objects.create(
                invoice=invoice,
                field_name="delivered_quantity",
                previous_value=previous_value,
                new_value=str(new_quantity),
                corrected_by=actor,
                reason=reason,
            )
        return invoice
