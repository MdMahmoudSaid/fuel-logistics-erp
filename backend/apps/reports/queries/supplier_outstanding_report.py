# SupplierOutstandingReportQuery - "supplier outstanding report"
# (ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md Etape 4/6).
#
# Mirrors CustomerOutstandingReportQuery on the purchasing side: total of
# non-cancelled SupplierOrder.total_amount minus total SupplierPayment for
# each supplier with at least one order.

from decimal import Decimal

from django.db.models import Sum

from apps.finance.models import SupplierPayment
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier

FIELDS = ["supplier", "outstanding"]
ZERO = Decimal("0.00")


class SupplierOutstandingReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls) -> list[dict]:
        supplier_ids = (
            SupplierOrder.objects.exclude(status=SupplierOrder.Status.CANCELLED)
            .values_list("supplier_id", flat=True)
            .distinct()
        )
        rows = []
        for supplier in Supplier.objects.filter(id__in=supplier_ids):
            total_purchased = (
                SupplierOrder.objects.filter(supplier=supplier)
                .exclude(status=SupplierOrder.Status.CANCELLED)
                .aggregate(total=Sum("total_amount"))["total"]
                or ZERO
            )
            total_paid = (
                SupplierPayment.objects.filter(supplier=supplier).aggregate(total=Sum("amount"))[
                    "total"
                ]
                or ZERO
            )
            rows.append({"supplier": supplier.name, "outstanding": total_purchased - total_paid})
        return rows
