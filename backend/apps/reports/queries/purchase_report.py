# PurchaseReportQuery - "purchase report" (ERP_Specification.md Section 37;
# docs/PHASE_6_PLAN.md Etape 4/6).

from apps.purchasing.models import SupplierOrder

FIELDS = ["reference", "purchase_date", "supplier", "product", "quantity_litres", "unit_price", "total_amount", "status"]


class PurchaseReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, supplier_id=None, date_from=None, date_to=None) -> list[dict]:
        orders = SupplierOrder.objects.select_related("supplier", "product").order_by(
            "-purchase_date", "-id"
        )
        if supplier_id:
            orders = orders.filter(supplier_id=supplier_id)
        if date_from:
            orders = orders.filter(purchase_date__gte=date_from)
        if date_to:
            orders = orders.filter(purchase_date__lte=date_to)

        return [
            {
                "reference": order.reference,
                "purchase_date": order.purchase_date,
                "supplier": order.supplier.name,
                "product": order.product.name,
                "quantity_litres": order.quantity_litres,
                "unit_price": order.unit_price,
                "total_amount": order.total_amount,
                "status": order.status,
            }
            for order in orders
        ]
