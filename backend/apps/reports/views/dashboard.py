# DashboardViewSet (docs/PHASE_6_PLAN.md Etape 5;
# ERP_Implementation_Experience_Guide.md Section 9.6: "backend aggregates,
# not many frontend loops over raw records").

from decimal import Decimal

from django.db.models import F, Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    TransportPayment,
    TreasuryTransaction,
)
from apps.finance.services import (
    ControlledDebtPaymentService,
    ShareholderProfitPreviewService,
    WorkingCapitalService,
)
from apps.reports.date_range import resolve_date_range
from apps.reports.queries.customer_outstanding_report import CustomerOutstandingReportQuery
from apps.reports.queries.supplier_outstanding_report import SupplierOutstandingReportQuery
from apps.reports.queries.transporter_outstanding_report import (
    TransporterOutstandingReportQuery,
)
from apps.reports.serialization import decimals_to_str
from apps.reports.services.profit import TripProfitService
from apps.reports.services.stock import TheoreticalStockService
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter
from apps.trips.models import Trip

ZERO = Decimal("0.00")

# Dashboard recette fix (2026-09-04): "Depenses generales payees" must never
# include a trip-linked fee (douane/transit/transit routiere/chargement/
# transport/frontiere), even one that happens to have no ExpenseAllocation
# row yet (an edge case the allocation-only filter alone would miss) - these
# are the 6 is_system=True category codes (finance.0014_expensecategory
# seed data / docs/superpowers/specs/2026-09-02-business-corrections-6-
# phases-design.md Phase 3), reused here as the same hardcoded values other
# services (ControlledDebtPaymentService) already key off, never a new
# lookup path.
_TRIP_EXPENSE_CATEGORIES = {
    Expense.Category.CUSTOMS,
    Expense.Category.TRANSIT,
    Expense.Category.ROAD_TRANSIT,
    Expense.Category.TRANSPORT,
    Expense.Category.LOADING,
    Expense.Category.ROAD,
}


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

        # Same reste-a-payer figures as the "Nouveau paiement" screen
        # (ControlledDebtPaymentService.get_payable_debts): amount minus
        # what's actually been disbursed via the TreasuryTransaction ledger,
        # grouped by the same expense-category buckets the payment screen
        # pays against. TRANSPORT-category expenses are excluded because
        # debts.transporters (TransporterOutstandingReportQuery) already
        # fully represents transporter liability; IMPORT_INTENTION has no
        # payable-debt bucket and is intentionally excluded here too.
        customs_total = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.CUSTOMS
        )["remaining_amount"]
        transit_total = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.TRANSIT
        )["remaining_amount"]
        road_transit_total = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.ROAD_TRANSIT
        )["remaining_amount"]
        border_total = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.BORDER
        )["remaining_amount"]
        loading_total = ControlledDebtPaymentService.describe_expense_group(
            ControlledDebtPaymentService.LOADING
        )["remaining_amount"]
        other_total = border_total + loading_total

        debts = {
            "total": (
                supplier_total
                + transporter_total
                + customs_total
                + transit_total
                + road_transit_total
                + other_total
            ),
            "suppliers": {"total": supplier_total, "rows": supplier_rows},
            "transporters": {"total": transporter_total, "rows": transporter_rows},
            "customs": customs_total,
            "transit": transit_total,
            "road_transit": road_transit_total,
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
        cash_rows = [
            {"cash_account": account.name, "balance": account.current_balance}
            for account in CashAccount.objects.filter(is_active=True)
        ]
        cash_amounts = {
            "total": sum((row["balance"] for row in cash_rows), ZERO),
            "rows": cash_rows,
        }

        # Summary only (design doc
        # 2026-08-26-benefices-associes-refinement-design.md) - point-in-time
        # "currently outstanding" snapshots like debts/customer_amounts
        # above, not scoped by date_from/date_to. The Benefices page
        # (Actionnaires/Associes) stays the single detailed source; the
        # dashboard never breaks this down per trip or per shareholder.
        # Single call, fields reused below - avoids a second, possibly
        # divergent computation of distributable_result alongside the one
        # the Benefices page's profit-preview endpoint already uses
        # (ShareholderProfitPreviewService is the sole owner of that
        # formula).
        profit_preview = ShareholderProfitPreviewService.get_preview()
        shareholders_summary = {
            "current_profit": profit_preview["current_profit"],
            "distributable_result": profit_preview["distributable_result"],
            # Kept so the typed frontend API contract does not diverge;
            # deliberately not rendered on the dashboard (spec 2026-09-07 §3).
            # Since the invoice now bills the received quantity,
            # distributable_result no longer subtracts this term. The trip
            # detail still shows company_absorbed_loss_amount, but it reads it
            # from /api/trips/{id}/margin/, a different endpoint.
            "total_company_absorbed_loss": profit_preview["total_company_absorbed_loss"],
            "total_withdrawn": ShareholderWithdrawal.objects.aggregate(total=Sum("amount"))[
                "total"
            ]
            or ZERO,
            "remaining_undistributed": ShareholderProfitShare.objects.exclude(
                distribution__status=ShareholderProfitDistribution.Status.CANCELLED
            ).aggregate(
                total=Sum(F("amount_due") - F("amount_withdrawn"))
            )["total"]
            or ZERO,
            "open_loans_total": sum(
                (
                    loan.remaining_amount
                    for loan in ShareholderLoan.objects.exclude(
                        status=ShareholderLoan.Status.REPAID
                    )
                ),
                ZERO,
            ),
        }

        period_collections = CustomerPayment.objects.all()
        if date_from:
            period_collections = period_collections.filter(payment_date__gte=date_from)
        if date_to:
            period_collections = period_collections.filter(payment_date__lte=date_to)

        # Dashboard recette fix (2026-09-04): "Depenses generales payees"
        # must count only general expenses, never a trip-linked fee - same
        # "no ExpenseAllocation" definition ShareholderProfitPreviewService.
        # get_preview() already uses for net_profit's general_expenses_paid,
        # plus the category exclusion above for the edge case of a trip-fee
        # category expense recorded with no allocation yet (allocations__
        # isnull=True alone would not catch that).
        paid_expenses = expenses.filter(
            status=Expense.Status.PAID, allocations__isnull=True
        ).exclude(category__in=_TRIP_EXPENSE_CATEGORIES)

        # Journal de tresorerie "Entrees / sorties" card (bug fix,
        # docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
        # design.md follow-up): period_collections/period_paid_expenses
        # above only ever reflect CustomerPayment/paid Expense rows, so a
        # ShareholderContribution (or any other flow that posts straight to
        # TreasuryTransaction with no CustomerPayment/Expense behind it) was
        # invisible to that card even though it appears in the journal's
        # transaction list. period_treasury_in/out aggregate the same
        # TreasuryTransaction rows the journal list itself shows, so the
        # card can never disagree with the visible lines. is_transfer rows
        # are excluded - moving cash between the company's own bank/cash
        # accounts is not a real inflow/outflow.
        treasury_movements = TreasuryTransaction.objects.filter(is_transfer=False)
        if date_from:
            treasury_movements = treasury_movements.filter(date__gte=date_from)
        if date_to:
            treasury_movements = treasury_movements.filter(date__lte=date_to)
        period_treasury_in = (
            treasury_movements.filter(type=TreasuryTransaction.Type.MONEY_IN).aggregate(
                total=Sum("amount")
            )["total"]
            or ZERO
        )
        period_treasury_out = (
            treasury_movements.filter(type=TreasuryTransaction.Type.MONEY_OUT).aggregate(
                total=Sum("amount")
            )["total"]
            or ZERO
        )

        period_paid_expenses_total = (
            paid_expenses.aggregate(total=Sum("amount"))["total"] or ZERO
        )
        financial_summary = {
            "period_revenue": sales["revenue"],
            "period_collections": period_collections.aggregate(total=Sum("amount"))["total"]
            or ZERO,
            "period_paid_expenses": period_paid_expenses_total,
            "period_treasury_in": period_treasury_in,
            "period_treasury_out": period_treasury_out,
            # period_accounting_profit stays trips-only operational profit
            # (unchanged, still correct - just no longer the dashboard's
            # headline figure, see period_net_profit below). Kept for any
            # other consumer; page Benefices remains the place to see it.
            "period_accounting_profit": profit["total_margin"],
            # Dashboard recette fix (2026-09-04): the dashboard's headline
            # profit card must be net profit (operational minus general
            # expenses actually paid), not the raw operational figure -
            # same formula as ShareholderProfitPreviewService.get_preview()'s
            # net_profit, computed independently here since this section is
            # deliberately period-scoped (date_from/date_to) while that
            # service defaults to "since last validated distribution".
            "period_net_profit": profit["total_margin"] - period_paid_expenses_total,
            "current_treasury_balance": treasury_balance,
        }

        def _largest(rows, name_key):
            open_rows = [row for row in rows if row["outstanding"] > ZERO]
            if not open_rows:
                return None
            row = max(open_rows, key=lambda item: item["outstanding"])
            return {"name": row[name_key], "amount": row["outstanding"]}

        # net_balance-based party balances (docs/superpowers/specs/2026-08-31-
        # supplier-transporter-advances-design.md): describe_supplier_balance/
        # describe_transporter_balance is the single source of truth also used
        # by Nouveau paiement's payable-debts and the Grand livre pages, so the
        # Dashboard can never disagree with them.
        supplier_balances = [
            ControlledDebtPaymentService.describe_supplier_balance(supplier)
            for supplier in Supplier.objects.filter(is_active=True)
        ]
        supplier_net_total = sum((row["net_balance"] for row in supplier_balances), ZERO)

        transporter_balances = [
            ControlledDebtPaymentService.describe_transporter_balance(transporter)
            for transporter in Transporter.objects.filter(is_active=True)
        ]
        transporter_net_total = sum((row["net_balance"] for row in transporter_balances), ZERO)

        def _largest_negative(rows):
            negative_rows = [row for row in rows if row["net_balance"] < ZERO]
            if not negative_rows:
                return None
            row = min(negative_rows, key=lambda item: item["net_balance"])
            return {"name": row["label"], "amount": -row["net_balance"]}

        shareholder_balance = (
            shareholders_summary["remaining_undistributed"]
            - shareholders_summary["open_loans_total"]
        )
        party_balances = {
            "customers": {
                "balance": customer_amounts["total"],
                "open_count": len(
                    [row for row in customer_amounts["rows"] if row["outstanding"] > ZERO]
                ),
                "largest_open": _largest(customer_amounts["rows"], "customer"),
            },
            "suppliers": {
                "balance": supplier_net_total,
                "open_count": len([row for row in supplier_balances if row["net_balance"] != ZERO]),
                "largest_open": _largest_negative(supplier_balances),
            },
            "transporters": {
                "balance": transporter_net_total,
                "open_count": len(
                    [row for row in transporter_balances if row["net_balance"] != ZERO]
                ),
                "largest_open": _largest_negative(transporter_balances),
            },
            "shareholders": {
                "balance": shareholder_balance,
                "remaining_undistributed": shareholders_summary["remaining_undistributed"],
                "total_withdrawn": shareholders_summary["total_withdrawn"],
                "open_loans_total": shareholders_summary["open_loans_total"],
            },
            "customs_and_other": {
                "balance": -(customs_total + transit_total + road_transit_total + other_total),
                "customs": customs_total,
                "transit": transit_total,
                "road_transit": road_transit_total,
                "other": other_total,
            },
        }

        # Fond de roulement client (docs/superpowers/specs/2026-09-04-
        # recette-corrections-design.md, Section 3) - single source of
        # truth also used by ShareholderProfitPreviewService's
        # distributable_result, never a second formula.
        working_capital = WorkingCapitalService.get_working_capital()

        # Only trips that have physically arrived at the depot count as stock -
        # destination_type alone isn't enough: GOING_TO_COMPANY_STOCK/earlier
        # pipeline statuses haven't arrived yet, and a trip un-assigned from a
        # customer keeps its old status (QUANTITY_CONTROL, DELIVERED, ...) - see
        # trips/serializers.py _normalize_destination_type.
        stock_trips = (
            Trip.objects.filter(
                sale__isnull=True,
                destination_type=Trip.DestinationType.COMPANY_STOCK,
                status__in=[Trip.Status.ARRIVED_AT_COMPANY_STOCK, Trip.Status.STOCKED],
            )
            .select_related("truck", "supplier", "transporter", "product")
            .order_by("-loading_date", "-id")
        )
        stock_by_product = [
            {"product": row["product__name"], "quantity": row["quantity"]}
            for row in stock_trips.values("product__name")
            .annotate(quantity=Sum("quantity_loaded"))
            .order_by("product__name")
        ]
        company_stock = {
            "total_quantity": stock_trips.aggregate(total=Sum("quantity_loaded"))["total"]
            or ZERO,
            # Client request (2026-09-06): valorisation pipeline - see
            # TheoreticalStockService.get_company_stock_value() docstring
            # for the "prix de revient" formula (purchase + trip fees).
            "value": TheoreticalStockService.get_company_stock_value(),
            "trips_count": stock_trips.count(),
            "by_product": stock_by_product,
            "trips": [
                {
                    "id": trip.id,
                    "reference": trip.reference,
                    "truck": trip.truck.internal_id,
                    "supplier": trip.supplier.name,
                    "transporter": trip.transporter.name if trip.transporter_id else None,
                    "product": trip.product.name,
                    "remaining_quantity": trip.quantity_loaded,
                    "entry_date": trip.loading_date,
                    "status": trip.status,
                }
                for trip in stock_trips[:25]
            ],
        }

        # Client request (2026-09-06): "pipeline" cards - reliquat chez le
        # fournisseur (jamais charge) -> en cours (charge, pas encore
        # arrive) -> stock entreprise (arrive, valeur ci-dessus). Each is
        # its own dict so the frontend can hide a card outright when its
        # quantity is zero rather than show a dead "0" tile.
        supplier_reliquat = {
            "quantity": TheoreticalStockService.get_supplier_reliquats(),
            "value": TheoreticalStockService.get_supplier_reliquat_value(),
        }
        in_transit = {
            "quantity": TheoreticalStockService.get_in_transit_quantity(),
            "value": TheoreticalStockService.get_in_transit_value(),
        }

        action_items = [
            {
                "kind": "company_stock_without_customer",
                "label": "Trajet arrive au stock sans client",
                "target": "trip-detail",
                "object_id": trip.id,
                "reference": trip.reference,
            }
            for trip in stock_trips[:10]
        ]
        action_items.extend(
            {
                "kind": "blocked_trip",
                "label": "Trajet bloque ou necessitant une action",
                "target": "trip-detail",
                "object_id": trip.id,
                "reference": trip.reference,
            }
            for trip in Trip.objects.filter(status=Trip.Status.BLOCKED).order_by("-updated_at")[
                :10
            ]
        )

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
                    "cash_amounts": cash_amounts,
                    "shareholders_summary": shareholders_summary,
                    "financial_summary": financial_summary,
                    "party_balances": party_balances,
                    "working_capital": working_capital,
                    "company_stock": company_stock,
                    "supplier_reliquat": supplier_reliquat,
                    "in_transit": in_transit,
                    "action_items": action_items,
                }
            )
        )
