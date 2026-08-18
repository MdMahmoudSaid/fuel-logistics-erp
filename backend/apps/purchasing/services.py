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
    def get_purchase_loaded_quantity(purchase: SupplierOrder) -> Decimal:
        # Phase 2 stub: always 0 because Phase-3 loadings/trips don't exist
        # yet. Will become SUM(trips.quantity_loaded) for this order.
        return Decimal("0.00")

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
        # Phase 2 stub: no loadings/trips exist yet, so the full authorized
        # quantity is still available. Phase 3: authorized_quantity -
        # SUM(trips.quantity_loaded for this cession).
        return cession.authorized_quantity

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
