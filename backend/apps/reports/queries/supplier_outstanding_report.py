# SupplierOutstandingReportQuery - "supplier outstanding report"
# (ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md Etape 4/6).
#
# "Outstanding" per supplier is the same reste-a-payer figure as the
# "Nouveau paiement" screen (ControlledDebtPaymentService.describe_supplier,
# already advance-aware since docs/superpowers/specs/2026-08-31-supplier-
# transporter-advances-design.md), so this report, the payment screen, and
# the Dashboard never disagree - mirrors TransporterOutstandingReportQuery's
# alignment.

from decimal import Decimal

from apps.finance.services import ControlledDebtPaymentService
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier

FIELDS = ["supplier", "outstanding"]
ZERO = Decimal("0.00")


class SupplierOutstandingReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls) -> list[dict]:
        supplier_ids = (
            SupplierOrder.objects.filter(status=SupplierOrder.Status.CONFIRMED)
            .values_list("supplier_id", flat=True)
            .distinct()
        )
        rows = []
        for supplier in Supplier.objects.filter(id__in=supplier_ids):
            outstanding = ControlledDebtPaymentService.describe_supplier(supplier)["remaining_amount"]
            if outstanding > ZERO:
                rows.append({"supplier": supplier.name, "outstanding": outstanding})
        return rows
