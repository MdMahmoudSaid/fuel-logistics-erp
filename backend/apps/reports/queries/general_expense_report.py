# GeneralExpenseReportQuery - "rapport des depenses generales" (docs/superpowers/
# specs/2026-09-23-rapports-capital-dettes-creances-design.md, section 2).
#
# A general expense is any Expense whose category is not a trip-fee category
# (Expense.TRIP_FEE_CATEGORY_CODES). total/paid/remaining come from
# ControlledDebtPaymentService.describe_expense_settlement; CANCELLED rows are
# listed (traceability) with total only - the document builder leaves them out
# of every total (decision N5).

from collections import defaultdict
from decimal import Decimal

from apps.finance.models import Expense
from apps.finance.services import ControlledDebtPaymentService

ZERO = Decimal("0.00")

# Business columns only; the technical row["section"] key is not exported.
FIELDS = [
    "date",
    "category",
    "notes",
    "calculation_method",
    "count",
    "total_amount",
    "paid_amount",
    "remaining_amount",
    "status",
]


class GeneralExpenseReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, category=None, date_from=None, date_to=None) -> list[dict]:
        expenses = (
            Expense.objects.exclude(category__in=Expense.TRIP_FEE_CATEGORY_CODES)
            .prefetch_related("allocations__content_object")
            .order_by("-date", "-id")
        )
        if category:
            expenses = expenses.filter(category=category)
        if date_from:
            expenses = expenses.filter(date__gte=date_from)
        if date_to:
            expenses = expenses.filter(date__lte=date_to)

        rows, recap = [], defaultdict(lambda: {"count": 0, "total": ZERO, "paid": ZERO, "remaining": ZERO})
        for expense in expenses:
            settlement = ControlledDebtPaymentService.describe_expense_settlement(expense)
            cancelled = expense.status == Expense.Status.CANCELLED
            rows.append(
                {
                    "section": "expense",
                    "date": expense.date,
                    "category": expense.category,
                    "notes": expense.notes,
                    "calculation_method": expense.calculation_method,
                    "total_amount": settlement["total_amount"],
                    "paid_amount": None if cancelled else settlement["paid_amount"],
                    "remaining_amount": None if cancelled else settlement["remaining_amount"],
                    "status": expense.status,
                }
            )
            if not cancelled:
                bucket = recap[expense.category]
                bucket["count"] += 1
                bucket["total"] += settlement["total_amount"]
                bucket["paid"] += settlement["paid_amount"]
                bucket["remaining"] += settlement["remaining_amount"]

        for code in sorted(recap):
            bucket = recap[code]
            rows.append(
                {
                    "section": "category_total",
                    "category": code,
                    "count": bucket["count"],
                    "total_amount": bucket["total"],
                    "paid_amount": bucket["paid"],
                    "remaining_amount": bucket["remaining"],
                }
            )
        return rows
