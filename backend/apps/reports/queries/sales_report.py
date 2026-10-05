# SalesReportQuery - "sales report" (ERP_Specification.md Section 37;
# docs/PHASE_6_PLAN.md Etape 4/6).

from django.utils import timezone

from apps.sales.models import Sale

FIELDS = ["trip_reference", "date", "customer", "product", "delivered_quantity", "unit_selling_price", "subtotal"]


class SalesReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, customer_id=None, date_from=None, date_to=None) -> list[dict]:
        # A sale belongs to the day it was recorded (client decision
        # 2026-10-05), not to its trip's loading date.
        sales = Sale.objects.select_related("trip", "customer", "product").order_by(
            "-created_at", "-id"
        )
        if customer_id:
            sales = sales.filter(customer_id=customer_id)
        if date_from:
            sales = sales.filter(created_at__date__gte=date_from)
        if date_to:
            sales = sales.filter(created_at__date__lte=date_to)

        return [
            {
                "trip_reference": sale.trip.reference,
                "date": timezone.localdate(sale.created_at),
                "customer": sale.customer.name,
                "product": sale.product.name,
                "delivered_quantity": sale.delivered_quantity,
                "unit_selling_price": sale.unit_selling_price,
                "subtotal": sale.subtotal,
            }
            for sale in sales
        ]
