# CustomerOutstandingReportQuery - "customer outstanding report"
# (ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md Etape 4/6).
#
# One row per customer with at least one non-cancelled invoice, delegating
# to PaymentAllocationService.get_customer_outstanding() so this never
# re-derives the "total invoiced - total received" formula on its own
# (guide Section 9.1's "do not scatter formulas" applies to outstanding
# balances just as much as to margin).

from apps.customers.models import Customer
from apps.finance.services import PaymentAllocationService
from apps.sales.models import Invoice

FIELDS = ["customer", "outstanding"]


class CustomerOutstandingReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls) -> list[dict]:
        customer_ids = (
            Invoice.objects.exclude(status=Invoice.Status.CANCELLED)
            .values_list("sale__customer_id", flat=True)
            .distinct()
        )
        customers = Customer.objects.filter(id__in=customer_ids)
        return [
            {
                "customer": customer.name,
                "outstanding": PaymentAllocationService.get_customer_outstanding(customer),
            }
            for customer in customers
        ]
