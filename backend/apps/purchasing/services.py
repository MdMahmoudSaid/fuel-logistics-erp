# Business logic for the purchase -> cession -> reliquat chain (see
# docs/PHASE_2_PLAN.md Etape 4 and ERP_Implementation_Experience_Guide.md
# Section 5). Serializers/views must call into this service rather than
# recomputing these formulas themselves (guide §5.5: "do not duplicate
# formulas across serializers, views and frontend code").

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.purchasing.models import CessionLetter, SupplierOrder


class SupplierStockService:
    @staticmethod
    def confirmed_orders_queryset():
        return SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)

    @staticmethod
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
        """Dynamic calculation: purchased quantity - active/exhausted cessions.

        Never stored on SupplierOrder (see ERP_Implementation_Experience_Guide.md
        §5.1) so cancellations/corrections can never cause drift.
        """
        cessions_sum = purchase.cessions.exclude(
            status=CessionLetter.Status.CANCELLED
        ).aggregate(total=Sum("authorized_quantity"))["total"] or Decimal("0.00")
        return purchase.quantity_litres - cessions_sum

    @staticmethod
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
        """Lock the SupplierOrder row and validate that enough reliquat remains.

        Must run inside the same atomic block as the CessionLetter
        create/update it guards, per the concurrency rule in
        ERP_Implementation_Experience_Guide.md §5.4 / §15: two concurrent
        requests must never both pass validation and jointly over-allocate
        the order's quantity.
        """
        purchase = SupplierOrder.objects.select_for_update().get(pk=purchase_id)

        # Sum of cessions still consuming the reliquat, excluding the cession
        # being edited (so re-saving an existing cession at the same or a
        # smaller quantity doesn't double-count itself).
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
