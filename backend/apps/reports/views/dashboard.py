# DashboardViewSet (docs/PHASE_6_PLAN.md Etape 5;
# ERP_Implementation_Experience_Guide.md Section 9.6: "backend aggregates,
# not many frontend loops over raw records").

from decimal import Decimal

from django.db.models import Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.finance.models import BankAccount, CashAccount, Expense, TransportPayment
from apps.reports.date_range import resolve_date_range
from apps.reports.queries.customer_outstanding_report import CustomerOutstandingReportQuery
from apps.reports.queries.supplier_outstanding_report import SupplierOutstandingReportQuery
from apps.reports.queries.transporter_outstanding_report import (
    TransporterOutstandingReportQuery,
)
from apps.reports.serialization import decimals_to_str
from apps.reports.services.profit import TripProfitService
from apps.reports.services.stock import TheoreticalStockService
from apps.trips.models import Trip

ZERO = Decimal("0.00")

# Expense categories already captured elsewhere in the debts breakdown -
# TRANSPORT is excluded from "other debts" because debts.transporters
# (TransporterOutstandingReportQuery, based on TransportPayment) already
# fully represents transporter liability; counting Expense(category=
# TRANSPORT) too would double-count the same debt.
_OTHER_DEBT_EXCLUDED_CATEGORIES = [Expense.Category.CUSTOMS, Expense.Category.TRANSPORT]
_OUTSTANDING_EXPENSE_STATUSES = [Expense.Status.UNPAID, Expense.Status.PARTIALLY_PAID]


class DashboardViewSet(viewsets.ViewSet):
    """GET /api/dashboard/summary/?range=...&from=...&to=... - the 6
    indicator sections (Operations, Fuel, Sales, Transport, Finance,
    Profit), all computed here rather than assembled client-side."""

    permission_classes = [HasModulePermission]
    module = "reports"

    @action(detail=False, methods=["get"])
    def summary(self, request):
        date_from, date_to = resolve_date_range(request.query_params)

        trips = Trip.objects.all()
        if date_from:
            trips = trips.filter(loading_date__gte=date_from)
        if date_to:
            trips = trips.filter(loading_date__lte=date_to)

        sold_trips = list(
            trips.filter(sale__isnull=False).select_related("sale", "sale__customer")
        )

        operations = {
            "trips_count": trips.count(),
            "active_trips_count": trips.exclude(status__in=Trip.TERMINAL_STATUSES).count(),
            "delivered_trips_count": trips.filter(status=Trip.Status.DELIVERED).count(),
        }

        fuel = {
            "quantity_loaded": trips.aggregate(total=Sum("quantity_loaded"))["total"] or ZERO,
            "theoretical_stock": TheoreticalStockService.get_total_theoretical_stock(),
        }

        sales = {
            "sales_count": len(sold_trips),
            "revenue": sum((t.sale.subtotal for t in sold_trips), ZERO),
        }

        transport_payments = TransportPayment.objects.filter(trip__in=trips)
        transport = {
            "settlements_count": transport_payments.count(),
            "transport_cost": transport_payments.aggregate(total=Sum("net_amount"))["total"]
            or ZERO,
        }

        expenses = Expense.objects.exclude(status=Expense.Status.CANCELLED)
        if date_from:
            expenses = expenses.filter(date__gte=date_from)
        if date_to:
            expenses = expenses.filter(date__lte=date_to)
        treasury_balance = sum(
            (account.current_balance for account in BankAccount.objects.all()), ZERO
        ) + sum((account.current_balance for account in CashAccount.objects.all()), ZERO)
        finance = {
            "expenses_total": expenses.aggregate(total=Sum("amount"))["total"] or ZERO,
            "treasury_balance": treasury_balance,
        }

        profit = {
            "total_margin": sum(
                (TripProfitService.calculate_current_margin(trip) for trip in sold_trips), ZERO
            )
        }

        # debts / customer_amounts / bank_amounts are point-in-time
        # "currently outstanding" snapshots (total minus paid, as of now),
        # not period aggregates - deliberately NOT scoped by date_from/
        # date_to like the sections above. A debt from 3 months ago is
        # still owed today regardless of the dashboard's selected range.
        supplier_rows = SupplierOutstandingReportQuery.run()
        supplier_total = sum((row["outstanding"] for row in supplier_rows), ZERO)

        transporter_rows = TransporterOutstandingReportQuery.run()
        transporter_total = sum((row["outstanding"] for row in transporter_rows), ZERO)

        outstanding_expenses = Expense.objects.filter(
            status__in=_OUTSTANDING_EXPENSE_STATUSES
        )
        customs_total = (
            outstanding_expenses.filter(category=Expense.Category.CUSTOMS).aggregate(
                total=Sum("amount")
            )["total"]
            or ZERO
        )
        other_total = (
            outstanding_expenses.exclude(
                category__in=_OTHER_DEBT_EXCLUDED_CATEGORIES
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )

        debts = {
            "total": supplier_total + transporter_total + customs_total + other_total,
            "suppliers": {"total": supplier_total, "rows": supplier_rows},
            "transporters": {"total": transporter_total, "rows": transporter_rows},
            "customs": customs_total,
            "other": other_total,
        }

        customer_rows = CustomerOutstandingReportQuery.run()
        customer_amounts = {
            "total": sum((row["outstanding"] for row in customer_rows), ZERO),
            "rows": customer_rows,
        }

        bank_rows = [
            {"bank": account.name, "balance": account.current_balance}
            for account in BankAccount.objects.filter(is_active=True)
        ]
        bank_amounts = {
            "total": sum((row["balance"] for row in bank_rows), ZERO),
            "rows": bank_rows,
        }

        return Response(
            decimals_to_str(
                {
                    "date_from": date_from,
                    "date_to": date_to,
                    "operations": operations,
                    "fuel": fuel,
                    "sales": sales,
                    "transport": transport,
                    "finance": finance,
                    "profit": profit,
                    "debts": debts,
                    "customer_amounts": customer_amounts,
                    "bank_amounts": bank_amounts,
                }
            )
        )
