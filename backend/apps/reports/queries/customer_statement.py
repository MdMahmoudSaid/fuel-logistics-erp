# CustomerStatementQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7).
#
# Raw query service, not a serializer/view: merges a customer's non-
# cancelled Invoice rows (debit) and CustomerPayment rows (credit) into one
# chronological statement with a running balance, mirroring
# PaymentAllocationService.get_customer_outstanding()'s "total invoiced -
# total received" formula one line at a time instead of as a single total.

from apps.finance.models import CustomerPayment
from apps.sales.models import Invoice

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


class CustomerStatementQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, customer_id, date_from=None, date_to=None) -> list[dict]:
        invoices = Invoice.objects.filter(sale__customer_id=customer_id).exclude(
            status=Invoice.Status.CANCELLED
        )
        payments = CustomerPayment.objects.filter(customer_id=customer_id)
        if date_from:
            invoices = invoices.filter(issued_date__gte=date_from)
            payments = payments.filter(payment_date__gte=date_from)
        if date_to:
            invoices = invoices.filter(issued_date__lte=date_to)
            payments = payments.filter(payment_date__lte=date_to)

        entries = [
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
        entries.sort(key=lambda entry: entry["sort_key"])

        balance = 0
        rows = []
        for entry in entries:
            balance += (entry["debit"] or 0) - (entry["credit"] or 0)
            rows.append(
                {
                    "date": entry["date"],
                    "type": entry["type"],
                    "reference": entry["reference"],
                    "debit": entry["debit"],
                    "credit": entry["credit"],
                    "balance": balance,
                }
            )
        return rows
