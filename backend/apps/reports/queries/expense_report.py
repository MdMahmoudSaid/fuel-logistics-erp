# ExpenseReportQuery - "expense report" (ERP_Specification.md Section 37;
# docs/PHASE_6_PLAN.md Etape 4/6).

from apps.finance.models import Expense

FIELDS = ["date", "category", "amount", "calculation_method", "status"]


class ExpenseReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, category=None, date_from=None, date_to=None) -> list[dict]:
        expenses = Expense.objects.exclude(status=Expense.Status.CANCELLED).order_by(
            "-date", "-id"
        )
        if category:
            expenses = expenses.filter(category=category)
        if date_from:
            expenses = expenses.filter(date__gte=date_from)
        if date_to:
            expenses = expenses.filter(date__lte=date_to)

        return [
            {
                "date": expense.date,
                "category": expense.category,
                "amount": expense.amount,
                "calculation_method": expense.calculation_method,
                "status": expense.status,
            }
            for expense in expenses
        ]
