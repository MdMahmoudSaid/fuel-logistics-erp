# SupplierStatementQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7).
#
# Mirrors CustomerStatementQuery on the purchasing side: confirmed
# SupplierOrder rows (debit, what the company owes) merged chronologically
# with SupplierPayment rows (credit, what has been paid) into one running
# balance.

from apps.finance.models import SupplierPayment
from apps.purchasing.models import SupplierOrder

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


class SupplierStatementQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, supplier_id, date_from=None, date_to=None) -> list[dict]:
        orders = SupplierOrder.objects.filter(
            supplier_id=supplier_id,
            status=SupplierOrder.Status.CONFIRMED,
        )
        payments = SupplierPayment.objects.filter(supplier_id=supplier_id)
        if date_from:
            orders = orders.filter(purchase_date__gte=date_from)
            payments = payments.filter(payment_date__gte=date_from)
        if date_to:
            orders = orders.filter(purchase_date__lte=date_to)
            payments = payments.filter(payment_date__lte=date_to)

        entries = [
            {
                "date": order.purchase_date,
                "type": "PURCHASE",
                "reference": order.reference,
                "debit": order.total_amount,
                "credit": None,
                "sort_key": (order.purchase_date, 0, order.id),
            }
            for order in orders
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
