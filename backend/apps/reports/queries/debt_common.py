# Shared row builders for the trip-fee and general debt reports (docs/superpowers/
# specs/2026-09-23-rapports-capital-dettes-creances-design.md, decision N6).
#
# Amounts (total / paid / remaining) come ONLY from the lines returned by
# ControlledDebtPaymentService.get_payable_debts() - the same call as the
# "Nouveau paiement" screen. Date / references / notes are display-only and are
# read from the source object found by the line's id (one query per model).

from apps.finance.models import Expense, TransportPayment
from apps.finance.services import ControlledDebtPaymentService as Debts
from apps.purchasing.models import SupplierOrder

# The five official trip-fee debt types, in the service's own order.
FEE_TYPES = [
    debt_type
    for debt_type in Debts.supported_debt_types()
    if debt_type not in (Debts.SUPPLIER, Debts.TRANSPORTER)
]


def _settlement_status(line) -> str:
    return "PARTIALLY_PAID" if line["paid_amount"] > 0 else "UNPAID"


def _amounts(line) -> dict:
    return {
        "total_amount": line["total_amount"],
        "paid_amount": line["paid_amount"],
        "remaining_amount": line["remaining_amount"],
    }


def fee_debt_rows(fee_types) -> list[dict]:
    lines = [
        (debt_type, line)
        for debt_type in fee_types
        for group in Debts.get_payable_debts(debt_type)
        for line in group["lines"]
    ]
    expenses = Expense.objects.prefetch_related("allocations__content_object").in_bulk(
        [line["id"] for _, line in lines]
    )
    rows = []
    for debt_type, line in lines:
        expense = expenses[line["id"]]
        trips = [
            allocation.content_object.reference
            for allocation in expense.allocations.all()
            if getattr(allocation.content_object, "reference", None)
        ]
        rows.append(
            {
                "fee_type": debt_type,
                "date": expense.date,
                "trips": ", ".join(trips) or None,
                "notes": expense.notes,
                **_amounts(line),
                "status": line["status"],
            }
        )
    return rows


def supplier_debt_rows() -> list[dict]:
    lines = [line for group in Debts.get_payable_debts(Debts.SUPPLIER) for line in group["lines"]]
    orders = SupplierOrder.objects.select_related("supplier").in_bulk([line["id"] for line in lines])
    return [
        {
            "supplier": orders[line["id"]].supplier.name,
            "reference": orders[line["id"]].reference,
            "date": orders[line["id"]].purchase_date,
            **_amounts(line),
            "status": _settlement_status(line),
        }
        for line in lines
    ]


def transporter_debt_rows() -> list[dict]:
    lines = [line for group in Debts.get_payable_debts(Debts.TRANSPORTER) for line in group["lines"]]
    payments = TransportPayment.objects.select_related("trip", "transporter").in_bulk(
        [line["id"] for line in lines]
    )
    return [
        {
            "transporter": payments[line["id"]].transporter.name,
            "trip_reference": payments[line["id"]].trip.reference,
            "date": payments[line["id"]].created_at.date(),
            **_amounts(line),
            "status": _settlement_status(line),
        }
        for line in lines
    ]
