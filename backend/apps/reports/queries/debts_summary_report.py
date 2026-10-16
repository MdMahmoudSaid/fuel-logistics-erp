# DebtsSummaryReportQuery - "ce que nous devons": ONE line per party the
# company owes money to, as of today (the period params are accepted and
# ignored). Every amount comes from the services behind the payment screens:
#
#   - supplier / transporter: get_payable_debts() remaining (already net of
#     consumed advances and including "Nouvelle dette" rows);
#   - trip fees: one line per fee bucket (customs, transit, ...);
#   - customer: the credit the customer has paid ahead (negative outstanding).
#
# - shareholders: one line per associate for the capital contributions not
#   given back and the validated profit shares not yet withdrawn (client
#   decision 2026-10-16: the company owes it to them until they withdraw it).

from decimal import Decimal

from apps.core.request_cache import memoize_per_request
from apps.customers.models import Customer
from apps.finance.models import CustomerPayment, OpeningDebt
from apps.finance.services import ControlledDebtPaymentService as Debts
from apps.finance.services import PaymentAllocationService, ShareholderLedgerService
from apps.reports.queries.debt_common import FEE_TYPES
from apps.sales.models import Invoice

FIELDS = ["party_type", "party", "amount"]
ZERO = Decimal("0.00")


def customer_ids_with_activity() -> set:
    """Customers that ever had an invoice, a payment or an opening debt."""
    return (
        set(Invoice.objects.exclude(status=Invoice.Status.CANCELLED).values_list("sale__customer_id", flat=True))
        | set(CustomerPayment.objects.exclude(is_reversed=True).values_list("customer_id", flat=True))
        | set(
            OpeningDebt.objects.filter(cancelled_at__isnull=True, customer__isnull=False)
            .values_list("customer_id", flat=True)
        )
    )


class DebtsSummaryReportQuery:
    FIELDS = FIELDS

    @classmethod
    @memoize_per_request
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        rows = [
            {"party_type": "supplier", "party": group["label"], "amount": group["remaining_amount"]}
            for group in Debts.get_payable_debts(Debts.SUPPLIER)
        ]
        rows += [
            {"party_type": "transporter", "party": group["label"], "amount": group["remaining_amount"]}
            for group in Debts.get_payable_debts(Debts.TRANSPORTER)
        ]
        for fee_type in FEE_TYPES:
            for group in Debts.get_payable_debts(fee_type):
                if group["remaining_amount"] > ZERO:
                    rows.append({"party_type": f"fee_{fee_type}", "party": None, "amount": group["remaining_amount"]})
        for customer in Customer.objects.filter(id__in=customer_ids_with_activity()).order_by("name", "id"):
            outstanding = PaymentAllocationService.get_customer_outstanding(customer)
            if outstanding < ZERO:
                rows.append({"party_type": "customer_credit", "party": customer.name, "amount": -outstanding})
        for shareholder in ShareholderLedgerService.get_company_dues()["shareholders"]:
            rows.append({"party_type": "shareholder", "party": shareholder["name"], "amount": shareholder["amount"]})
        return rows
