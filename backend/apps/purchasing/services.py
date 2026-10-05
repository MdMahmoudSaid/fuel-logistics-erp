# Business logic for the purchase -> cession -> reliquat chain (see
# docs/PHASE_2_PLAN.md Etape 4 and ERP_Implementation_Experience_Guide.md
# Section 5). Serializers/views must call into this service rather than
# recomputing these formulas themselves (guide §5.5: "do not duplicate
# formulas across serializers, views and frontend code").

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.core.request_cache import memoize_per_request
from apps.purchasing.models import CessionLetter, SupplierOrder


class SupplierStockService:
    @staticmethod
    def confirmed_orders_queryset():
        return SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)

    @staticmethod
    @memoize_per_request
    def get_purchase_loaded_quantity(purchase: SupplierOrder) -> Decimal:
        """SUM(trips.quantity_loaded) for this order, excluding cancelled
        trips (Phase 3: apps.trips.Trip now exists). Imported lazily to keep
        purchasing - a lower layer than trips in the dependency graph - free
        of a module-level import on a higher layer (guide §5.1: derive from
        source transactions, never a mutable cached field)."""
        from apps.trips.models import Trip

        return Trip.objects.filter(supplier_order=purchase).exclude(
            status=Trip.Status.CANCELLED
        ).aggregate(total=Sum("quantity_loaded"))["total"] or Decimal("0.00")

    @staticmethod
    def get_purchase_reliquat(purchase: SupplierOrder) -> Decimal:
        """Dynamic calculation: purchased quantity - quantity actually
        loaded onto a trip (excluding cancelled trips).

        Bug fix (client business rule, confirmed 2026-09-06): a cession
        letter *authorizes* loading up to a quantity, it does not itself
        remove fuel from the supplier - the reliquat must only shrink once
        litres are physically loaded. Before this fix the reliquat was
        computed as purchased - cessions, so issuing a cession for the full
        purchased quantity made the reliquat read 0 even though no truck had
        loaded anything yet. Example confirmed with the client: purchase
        200,000 L, cession 200,000 L, one trip loads 100,000 L -> reliquat
        must read 100,000 L, not 0.

        This is a distinct balance from the "how much more can still be
        authorized via a new cession" cap enforced by
        validate_and_lock_reliquat() below, which intentionally still sums
        active cessions against the purchased quantity (a cession letter can
        never promise more fuel than was actually bought) - the two numbers
        are allowed to diverge (cession commitments issued but not yet
        loaded still show up there, not here) and each has its own use.

        Never stored on SupplierOrder (see ERP_Implementation_Experience_Guide.md
        §5.1) so cancellations/corrections can never cause drift.
        """
        loaded = SupplierStockService.get_purchase_loaded_quantity(purchase)
        return purchase.quantity_litres - loaded

    @staticmethod
    def get_purchase_loaded_amount(purchase: SupplierOrder) -> Decimal:
        """Monetary value of the quantity actually loaded against `purchase`
        so far: loaded_quantity x unit_price, plus a proportional share of
        optional_costs (loaded_quantity / quantity_litres of the order's
        total optional_costs).

        Business rule reversal (client request, 2026-09-10, reverting the
        2026-09-06 rule): this is no longer what becomes the payable debt to
        the supplier - see ControlledDebtPaymentService.describe_supplier_order
        in apps.finance.services, which now books the full confirmed order
        total as debt immediately on confirmation, regardless of how much
        has been loaded. This method stays useful on its own (the
        counterpart get_purchase_reliquat_amount() below is defined in terms
        of it) as "how much of the paid-for fuel has physically left the
        supplier so far".
        """
        if purchase.quantity_litres <= Decimal("0.00"):
            return Decimal("0.00")
        loaded = SupplierStockService.get_purchase_loaded_quantity(purchase)
        fuel_amount = loaded * purchase.unit_price
        optional_costs = purchase.optional_costs or Decimal("0.00")
        prorated_costs = (
            (optional_costs * loaded / purchase.quantity_litres)
            if optional_costs
            else Decimal("0.00")
        )
        return (fuel_amount + prorated_costs).quantize(Decimal("0.01"))

    @staticmethod
    def get_purchase_reliquat_amount(purchase: SupplierOrder) -> Decimal:
        """Monetary value of the unloaded reliquat: fuel still sitting at
        the supplier, not yet loaded onto a trip.

        Added 2026-09-10 (client request), corrected 2026-09-14: the whole
        order is booked as an open DEBT on confirmation (see
        get_purchase_loaded_amount() above) - that is not the same as being
        PAID for. This raw value is only a candidate for WorkingCapital-
        Service's "Fond de roulement client" asset line, capped there by
        how much has actually been paid to the supplier so far (see
        WorkingCapitalService.get_supplier_pipeline_breakdown) - an unpaid
        order's reliquat must NOT also count as an asset on top of the open
        debt, or the same unpaid litres get counted twice. Computed as
        total_amount - loaded_amount (not reliquat_quantity x unit_price
        recomputed independently) so the two halves always sum exactly back
        to total_amount, immune to prorated-optional-costs rounding drift.
        """
        return purchase.total_amount - SupplierStockService.get_purchase_loaded_amount(purchase)

    @staticmethod
    @memoize_per_request
    def get_purchase_in_transit_amount(purchase: SupplierOrder) -> Decimal:
        """Monetary value, at the order's own unit_price, of `purchase`'s
        loaded litres currently "en cours" - on a truck, not yet arrived at
        either final destination (company stock or client) and not yet
        sold. Mirrors apps.reports.services.stock.TheoreticalStockService.
        _in_transit_trips()'s definition exactly, scoped to one order, so
        the two never drift apart.

        Like get_purchase_reliquat_amount() above, this is a raw candidate
        value only - WorkingCapitalService.get_supplier_pipeline_breakdown
        caps it by what has actually been paid to the supplier, to avoid
        double-counting against the still-open debt.
        """
        from apps.trips.models import Trip

        quantity = (
            Trip.objects.filter(supplier_order=purchase, sale__isnull=True)
            .exclude(
                status__in={
                    Trip.Status.ARRIVED_AT_COMPANY_STOCK,
                    Trip.Status.STOCKED,
                    *Trip.NON_OCCUPYING_STATUSES,
                }
            )
            .aggregate(total=Sum("quantity_loaded"))["total"]
            or Decimal("0.00")
        )
        return (quantity * purchase.unit_price).quantize(Decimal("0.01"))

    @staticmethod
    @memoize_per_request
    def get_purchase_company_stock_amount(purchase: SupplierOrder) -> Decimal:
        """Monetary value, at the order's own unit_price, of `purchase`'s
        loaded litres that have arrived and are sitting in the company's
        own stock (not yet sold). Mirrors apps.reports.services.stock.
        TheoreticalStockService._company_stock_trips()'s definition exactly
        (destination COMPANY_STOCK, status ARRIVED_AT_COMPANY_STOCK/
        STOCKED), scoped to one order, valued at the pure purchase price
        only - unlike the Dashboard's "Stock entreprise" card, this
        deliberately excludes transport/customs costs (client decision,
        2026-09-14): those are separate open debts already added in full to
        WorkingCapitalService's total, so folding them into this value too
        would double-count them a second time.

        Raw candidate value only - see get_purchase_in_transit_amount()
        above for the same caveat re: capping by amount paid.
        """
        from apps.trips.models import Trip

        quantity = (
            Trip.objects.filter(
                supplier_order=purchase,
                sale__isnull=True,
                destination_type=Trip.DestinationType.COMPANY_STOCK,
                status__in=[Trip.Status.ARRIVED_AT_COMPANY_STOCK, Trip.Status.STOCKED],
            ).aggregate(total=Sum("quantity_loaded"))["total"]
            or Decimal("0.00")
        )
        return (quantity * purchase.unit_price).quantize(Decimal("0.01"))

    @staticmethod
    @memoize_per_request
    def get_cession_remaining(cession: CessionLetter) -> Decimal:
        """authorized_quantity - SUM(trips.quantity_loaded against this
        cession), excluding cancelled trips - never a stored/mutable field
        (guide §5.3: "Do not make remaining_quantity the authoritative
        value")."""
        from apps.trips.models import Trip

        loaded = Trip.objects.filter(cession_letter=cession).exclude(
            status=Trip.Status.CANCELLED
        ).aggregate(total=Sum("quantity_loaded"))["total"] or Decimal("0.00")
        return cession.authorized_quantity - loaded

    @staticmethod
    @transaction.atomic
    def validate_and_lock_reliquat(
        purchase_id: int, requested_qty: Decimal, exclude_cession_id: int | None = None
    ) -> SupplierOrder:
        """Lock the SupplierOrder row and validate that a new/edited cession
        never promises more fuel than was actually purchased.

        Despite the name, this guards a different balance from
        get_purchase_reliquat() above (which now tracks purchased - loaded,
        the client-facing "reliquat"): this one tracks purchased - already
        cessioned, i.e. "how much more can still be authorized via a
        cession letter". That cap is still correct and unchanged - a
        cession letter can never authorize more than was bought, regardless
        of how much of it has been loaded yet - it's only the *display*
        reliquat that moved to a load-based definition.

        Must run inside the same atomic block as the CessionLetter
        create/update it guards, per the concurrency rule in
        ERP_Implementation_Experience_Guide.md §5.4 / §15: two concurrent
        requests must never both pass validation and jointly over-allocate
        the order's quantity.
        """
        purchase = SupplierOrder.objects.select_for_update().get(pk=purchase_id)

        # Sum of cessions still consuming the purchased quantity, excluding
        # the cession being edited (so re-saving an existing cession at the
        # same or a smaller quantity doesn't double-count itself).
        queryset = purchase.cessions.exclude(status=CessionLetter.Status.CANCELLED)
        if exclude_cession_id:
            queryset = queryset.exclude(pk=exclude_cession_id)

        cessions_sum = queryset.aggregate(total=Sum("authorized_quantity"))[
            "total"
        ] or Decimal("0.00")
        available_reliquat = purchase.quantity_litres - cessions_sum

        if requested_qty > available_reliquat:
            raise ValueError(
                f"Quantité demandée ({requested_qty} L) supérieure au reliquat "
                f"disponible ({available_reliquat} L)."
            )
        return purchase

    @staticmethod
    @transaction.atomic
    def validate_and_lock_cession_quantity(
        cession_id: int, requested_qty: Decimal, exclude_trip_id: int | None = None
    ) -> CessionLetter:
        """Lock the CessionLetter row and validate quantity_loaded against
        its own remaining balance - the Phase 3 counterpart of
        validate_and_lock_reliquat(), guarding Trip creation instead of
        CessionLetter creation (docs/PHASE_3_PLAN.md Etape 5;
        ERP_Implementation_Experience_Guide.md §5.4's concurrency scenario
        applied to loading rather than to issuing the cession itself).

        Cession remaining and purchase reliquat are two different balances
        (guide §1.3) - this never touches SupplierOrder.
        """
        from apps.trips.models import Trip

        cession = CessionLetter.objects.select_for_update().get(pk=cession_id)

        queryset = Trip.objects.filter(cession_letter=cession).exclude(
            status=Trip.Status.CANCELLED
        )
        if exclude_trip_id:
            queryset = queryset.exclude(pk=exclude_trip_id)

        loaded_sum = queryset.aggregate(total=Sum("quantity_loaded"))[
            "total"
        ] or Decimal("0.00")
        remaining = cession.authorized_quantity - loaded_sum

        if requested_qty > remaining:
            raise ValueError(
                f"Quantité chargée demandée ({requested_qty} L) supérieure au "
                f"reliquat de la cession ({remaining} L)."
            )
        return cession


class SupplierOrderAmendmentService:
    """Guards for correcting a CONFIRMED SupplierOrder's quantity/price/costs
    in place (client request 2026-09-24; previously the only way out was
    cancelling the order, which left every trip loaded on it untracked).

    An amendment is refused when it would strand something that already
    depends on the order - litres loaded on trips, active cession letters,
    cash paid to the supplier. Advance consumption is not a blocker: it is
    recomputed against the new total (AdvanceConsumptionService).
    """

    @staticmethod
    def validate(
        order: SupplierOrder,
        *,
        new_quantity: Decimal,
        new_total: Decimal,
    ) -> dict[str, str]:
        """Returns {field: message} (empty when the amendment is acceptable).

        Runs under a lock on the order row; callers must be inside the same
        atomic block as the save (SupplierOrderViewSet.update is)."""
        from apps.finance.services import ControlledDebtPaymentService

        order = SupplierOrder.objects.select_for_update().get(pk=order.pk)
        errors: dict[str, str] = {}

        if new_quantity != order.quantity_litres:
            loaded = SupplierStockService.get_purchase_loaded_quantity(order)
            cessioned = order.cessions.exclude(
                status=CessionLetter.Status.CANCELLED
            ).aggregate(total=Sum("authorized_quantity"))["total"] or Decimal("0.00")
            minimum = max(loaded, cessioned)
            if new_quantity < minimum:
                reasons = []
                if loaded > 0:
                    reasons.append(f"{loaded:.2f} L déjà chargés sur des trajets")
                if cessioned > 0:
                    reasons.append(f"{cessioned:.2f} L autorisés par des lettres de cession")
                errors["quantity_litres"] = (
                    f"Quantité minimale autorisée : {minimum:.2f} L "
                    f"({' ; '.join(reasons)})."
                )

        if "quantity_litres" not in errors:
            paid = ControlledDebtPaymentService.get_supplier_order_cash_paid(order)
            if new_total < paid:
                errors["quantity_litres" if new_quantity != order.quantity_litres else "unit_price"] = (
                    f"Le nouveau montant total ({new_total:.2f}) serait inférieur au montant "
                    f"déjà payé au fournisseur ({paid:.2f}). Annulez d'abord le paiement en trop."
                )
        return errors
