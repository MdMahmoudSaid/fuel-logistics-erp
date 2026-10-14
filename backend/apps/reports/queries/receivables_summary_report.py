# ReceivablesSummaryReportQuery - "ce qui nous est dû": ONE line per party that
# owes the company money, as of today (the period params are accepted and
# ignored):
#
#   - customer: get_customer_outstanding() when positive (invoices + "Nouvelle
#     dette" - receipts), the same figure as the customer outstanding report;
#   - supplier / transporter: the advances handed to them and not yet consumed
#     (AdvanceConsumptionService.open_*_advances, same as the party balance).
#
# Shareholder money is deliberately excluded (profit share / capital).

from decimal import Decimal

from apps.core.request_cache import memoize_per_request
from apps.customers.models import Customer
from apps.finance.models import SupplierAdvance, TransporterAdvance
from apps.finance.services import AdvanceConsumptionService, PaymentAllocationService
from apps.reports.queries.debts_summary_report import customer_ids_with_activity
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter

FIELDS = ["party_type", "party", "amount"]
ZERO = Decimal("0.00")


class ReceivablesSummaryReportQuery:
    FIELDS = FIELDS

    @classmethod
    @memoize_per_request
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        rows = []
        for customer in Customer.objects.filter(id__in=customer_ids_with_activity()).order_by("name", "id"):
            outstanding = PaymentAllocationService.get_customer_outstanding(customer)
            if outstanding > ZERO:
                rows.append({"party_type": "customer", "party": customer.name, "amount": outstanding})
        for supplier in Supplier.objects.filter(
            id__in=SupplierAdvance.objects.values_list("supplier_id", flat=True)
        ).order_by("name", "id"):
            open_advances = sum(
                (a.remaining_amount for a in AdvanceConsumptionService.open_supplier_advances(supplier)), ZERO
            )
            if open_advances > ZERO:
                rows.append({"party_type": "supplier_advance", "party": supplier.name, "amount": open_advances})
        for transporter in Transporter.objects.filter(
            id__in=TransporterAdvance.objects.values_list("transporter_id", flat=True)
        ).order_by("name", "id"):
            open_advances = sum(
                (a.remaining_amount for a in AdvanceConsumptionService.open_transporter_advances(transporter)),
                ZERO,
            )
            if open_advances > ZERO:
                rows.append({"party_type": "transporter_advance", "party": transporter.name, "amount": open_advances})
        return rows
