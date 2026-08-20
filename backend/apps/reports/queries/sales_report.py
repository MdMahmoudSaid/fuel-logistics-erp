# SalesReportQuery - "sales report" (ERP_Specification.md Section 37;
# docs/PHASE_6_PLAN.md Etape 4/6).

from apps.sales.models import Sale

FIELDS = ["trip_reference", "date", "customer", "product", "delivered_quantity", "unit_selling_price", "subtotal"]


class SalesReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, customer_id=None, date_from=None, date_to=None) -> list[dict]:
        sales = Sale.objects.select_related("trip", "customer", "product").order_by(
            "-trip__loading_date", "-id"
        )
        if customer_id:
            sales = sales.filter(customer_id=customer_id)
        if date_from:
            sales = sales.filter(trip__loading_date__gte=date_from)
        if date_to:
            sales = sales.filter(trip__loading_date__lte=date_to)

        return [
            {
                "trip_reference": sale.trip.reference,
                "date": sale.trip.loading_date,
                "customer": sale.customer.name,
                "product": sale.product.name,
                "delivered_quantity": sale.delivered_quantity,
                "unit_selling_price": sale.unit_selling_price,
                "subtotal": sale.subtotal,
            }
            for sale in sales
        ]
