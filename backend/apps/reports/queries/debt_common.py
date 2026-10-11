# Shared row builders for the trip-fee and general debt reports (docs/superpowers/
# specs/2026-09-23-rapports-capital-dettes-creances-design.md, decision N6).
#
# Amounts (total / paid / remaining) come ONLY from the lines returned by
# ControlledDebtPaymentService.get_payable_debts() - the same call as the
# "Nouveau paiement" screen. Date / references / notes are display-only and are
# read from the source object found by the line's id (one query per model).

from apps.finance.models import Expense, OpeningDebt, TransportPayment
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


def _opening_debts(lines):
    """OpeningDebt rows ("Nouvelle dette") behind the lines tagged so - their
    ids can collide with order/settlement ids, hence the `source` tag."""
    return OpeningDebt.objects.select_related("supplier", "transporter").in_bulk(
        [line["id"] for line in lines if line.get("source") == "opening_debt"]
    )


def supplier_debt_rows() -> list[dict]:
    lines = [line for group in Debts.get_payable_debts(Debts.SUPPLIER) for line in group["lines"]]
    orders = SupplierOrder.objects.select_related("supplier").in_bulk(
        [line["id"] for line in lines if line.get("source") != "opening_debt"]
    )
    opening = _opening_debts(lines)
    rows = []
    for line in lines:
        if line.get("source") == "opening_debt":
            debt = opening[line["id"]]
            supplier, reference, date = debt.supplier.name, debt.reference or None, debt.date
        else:
            order = orders[line["id"]]
            supplier, reference, date = order.supplier.name, order.reference, order.purchase_date
        rows.append(
            {
                "supplier": supplier,
                "reference": reference,
                "date": date,
                **_amounts(line),
                "status": _settlement_status(line),
            }
        )
    return rows


def transporter_debt_rows() -> list[dict]:
    lines = [line for group in Debts.get_payable_debts(Debts.TRANSPORTER) for line in group["lines"]]
    payments = TransportPayment.objects.select_related("trip", "transporter").in_bulk(
        [line["id"] for line in lines if line.get("source") != "opening_debt"]
    )
    opening = _opening_debts(lines)
    rows = []
    for line in lines:
        if line.get("source") == "opening_debt":
            debt = opening[line["id"]]
            transporter, trip_reference, date = debt.transporter.name, debt.reference or None, debt.date
        else:
            payment = payments[line["id"]]
            transporter = payment.transporter.name
            trip_reference, date = payment.trip.reference, payment.created_at.date()
        rows.append(
            {
                "transporter": transporter,
                "trip_reference": trip_reference,
                "date": date,
                **_amounts(line),
                "status": _settlement_status(line),
            }
        )
    return rows
