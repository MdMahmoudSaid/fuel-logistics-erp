# SupplierStatementQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7).
#
# Mirrors CustomerStatementQuery on the purchasing side: confirmed
# SupplierOrder rows (debit, what the company owes) merged chronologically
# with SupplierPayment rows (credit, what has been paid) into one running
# balance.

from apps.finance.models import OpeningDebt, SupplierAdvance, SupplierPayment
from apps.purchasing.models import SupplierOrder
from apps.reports.queries.statement_common import entries_of, opening_balance, statement_rows

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


class SupplierStatementQuery:
    FIELDS = FIELDS

    @staticmethod
    def _parties():
        from apps.suppliers.models import Supplier
        return Supplier.objects.order_by("name").values_list("id", "name")
    DIRECTION = 1  # debit - credit: a positive balance is money owed to the supplier

    @classmethod
    def _entries(cls, supplier_id) -> list[dict]:
        orders = SupplierOrder.objects.filter(
            supplier_id=supplier_id,
            status=SupplierOrder.Status.CONFIRMED,
        )
        # A cancelled payment (is_reversed=True) never really left treasury -
        # excluded so the running balance reflects what's currently true.
        payments = SupplierPayment.objects.filter(supplier_id=supplier_id).exclude(
            is_reversed=True
        )
        opening_debts = OpeningDebt.objects.filter(supplier_id=supplier_id, cancelled_at__isnull=True)
        # Advances handed over are money the supplier already holds: they
        # reduce what is owed, so the closing balance matches the ledger's
        # net balance (ControlledDebtPaymentService.describe_supplier_balance).
        advances = SupplierAdvance.objects.filter(supplier_id=supplier_id)
        return [
            {
                "date": advance.date,
                "type": "ADVANCE_PAID",
                "reference": advance.reference or f"AV-{advance.id}",
                "debit": None,
                "credit": advance.amount,
                "sort_key": (advance.date, 1, advance.id),
            }
            for advance in advances
        ] + [
            {
                "date": debt.date,
                "type": "OPENING_DEBT",
                "reference": debt.reference or f"DET-{debt.id}",
                "debit": debt.amount,
                "credit": None,
                "sort_key": (debt.date, -1, debt.id),
            }
            for debt in opening_debts
        ] + [
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

    @classmethod
    def opening_balance(cls, *, supplier_id=None, date_from=None, date_to=None):
        return opening_balance(entries_of(cls, supplier_id, cls._parties()), date_from=date_from, direction=cls.DIRECTION)

    @classmethod
    def run(cls, *, supplier_id=None, date_from=None, date_to=None) -> list[dict]:
        return statement_rows(
            entries_of(cls, supplier_id, cls._parties()), date_from=date_from, date_to=date_to, direction=cls.DIRECTION
        )
