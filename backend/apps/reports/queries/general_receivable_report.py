# GeneralReceivableReportQuery - "creances clients" (docs/superpowers/specs/
# 2026-09-23-rapports-capital-dettes-creances-design.md, section 5). Situation
# courante: the period params are accepted and ignored.
#
#   reste client = sum(non-cancelled invoices) - sum(all non-reversed payments)
#                = PaymentAllocationService.get_customer_outstanding(customer)
#
# Shown per customer: every non-cancelled invoice whose own remaining is not 0
# (PaymentAllocationService.get_invoice_outstanding's formula, computed in one
# grouped query), then one "unallocated credit" line that REDUCES the remaining:
#   credit = sum(non-reversed payments)
#            - sum(their allocations on non-cancelled invoices)
# so sum(invoice remainings) - credit == get_customer_outstanding.

from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum

from apps.customers.models import Customer
from apps.finance.models import CustomerPayment, PaymentAllocation
from apps.sales.models import Invoice

ZERO = Decimal("0.00")

FIELDS = [
    "customer",
    "line_type",
    "reference",
    "date",
    "trip_reference",
    "invoiced_amount",
    "received_amount",
    "remaining_amount",
]


class GeneralReceivableReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        invoices = (
            Invoice.objects.exclude(status=Invoice.Status.CANCELLED)
            .select_related("sale__customer", "sale__trip")
            .annotate(
                allocated=Sum(
                    "allocations__amount", filter=~Q(allocations__payment__is_reversed=True)
                )
            )
            .order_by("issued_date", "id")
        )
        invoiced = defaultdict(lambda: ZERO)
        invoice_lines = defaultdict(list)
        for invoice in invoices:
            customer_id = invoice.sale.customer_id
            allocated = invoice.allocated or ZERO
            invoiced[customer_id] += invoice.total_amount
            if invoice.total_amount - allocated != ZERO:
                invoice_lines[customer_id].append((invoice, allocated))

        received = {
            row["customer_id"]: row["total"]
            for row in CustomerPayment.objects.exclude(is_reversed=True)
            .values("customer_id")
            .annotate(total=Sum("amount"))
        }
        allocated_on_valid_invoices = {
            row["payment__customer_id"]: row["total"]
            for row in PaymentAllocation.objects.filter(
                payment__is_reversed=False, invoice__isnull=False
            )
            .exclude(invoice__status=Invoice.Status.CANCELLED)
            .values("payment__customer_id")
            .annotate(total=Sum("amount"))
        }

        rows = []
        for customer in Customer.objects.filter(id__in=set(invoiced) | set(received)).order_by("name", "id"):
            outstanding = invoiced[customer.id] - (received.get(customer.id) or ZERO)
            if outstanding == ZERO:
                continue
            credit = (received.get(customer.id) or ZERO) - (allocated_on_valid_invoices.get(customer.id) or ZERO)
            customer_rows = [
                {
                    "customer": customer.name,
                    "line_type": "invoice",
                    "reference": invoice.invoice_number,
                    "date": invoice.issued_date,
                    "trip_reference": ", ".join(x.trip.reference for x in invoice.all_sales),
                    "invoiced_amount": invoice.total_amount,
                    "received_amount": allocated,
                    "remaining_amount": invoice.total_amount - allocated,
                }
                for invoice, allocated in invoice_lines[customer.id]
            ]
            if credit != ZERO:
                customer_rows.append(
                    {
                        "customer": customer.name,
                        "line_type": "credit",
                        "reference": None,
                        "date": None,
                        "trip_reference": None,
                        "invoiced_amount": None,
                        "received_amount": credit,
                        "remaining_amount": -credit,
                    }
                )
            customer_rows.append(
                {
                    "customer": customer.name,
                    "line_type": "customer_total",
                    "reference": None,
                    "date": None,
                    "trip_reference": None,
                    "invoiced_amount": sum((r["invoiced_amount"] or ZERO for r in customer_rows), ZERO),
                    "received_amount": sum((r["received_amount"] for r in customer_rows), ZERO),
                    "remaining_amount": sum((r["remaining_amount"] for r in customer_rows), ZERO),
                }
            )
            rows.extend(customer_rows)
        return rows
