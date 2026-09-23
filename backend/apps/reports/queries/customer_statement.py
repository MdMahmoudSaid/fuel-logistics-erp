# CustomerStatementQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7).
#
# Raw query service, not a serializer/view: merges a customer's non-
# cancelled Invoice rows (debit) and CustomerPayment rows (credit) into one
# chronological statement with a running balance, mirroring
# PaymentAllocationService.get_customer_outstanding()'s "total invoiced -
# total received" formula one line at a time instead of as a single total.

from apps.finance.models import CustomerPayment
from apps.reports.queries.statement_common import opening_balance, statement_rows
from apps.sales.models import Invoice

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


class CustomerStatementQuery:
    FIELDS = FIELDS
    DIRECTION = 1  # debit - credit: a positive balance is money owed by the customer

    @classmethod
    def _entries(cls, customer_id) -> list[dict]:
        invoices = Invoice.objects.filter(sale__customer_id=customer_id).exclude(
            status=Invoice.Status.CANCELLED
        )
        payments = CustomerPayment.objects.filter(customer_id=customer_id)
        return [
            {
                "date": invoice.issued_date,
                "type": "INVOICE",
                "reference": invoice.invoice_number,
                "debit": invoice.total_amount,
                "credit": None,
                "sort_key": (invoice.issued_date, 0, invoice.id),
            }
            for invoice in invoices
        ] + [
            {
                "date": payment.payment_date,
                "type": "PAYMENT",
                "reference": payment.reference or f"PAY-{payment.id}",
                "debit": None,
                "credit": payment.amount,
                "sort_key": (payment.payment_date, 1, payment.id),
            }
            for payment in payments
        ]

    @classmethod
    def opening_balance(cls, *, customer_id, date_from=None, date_to=None):
        return opening_balance(cls._entries(customer_id), date_from=date_from, direction=cls.DIRECTION)

    @classmethod
    def run(cls, *, customer_id, date_from=None, date_to=None) -> list[dict]:
        return statement_rows(
            cls._entries(customer_id), date_from=date_from, date_to=date_to, direction=cls.DIRECTION
        )
