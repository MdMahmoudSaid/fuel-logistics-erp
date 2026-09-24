# ReportViewSet (docs/PHASE_6_PLAN.md Etape 5;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.date_range import resolve_date_range
from apps.reports.export import rows_to_csv, rows_to_xlsx
from apps.reports.queries.capital_report import CapitalReportQuery
from apps.reports.queries.customer_outstanding_report import CustomerOutstandingReportQuery
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.expense_report import ExpenseReportQuery
from apps.reports.queries.fuel_stock_report import FuelStockReportQuery
from apps.reports.queries.general_debt_report import GeneralDebtReportQuery
from apps.reports.queries.general_expense_report import GeneralExpenseReportQuery
from apps.reports.queries.general_receivable_report import GeneralReceivableReportQuery
from apps.reports.queries.loss_report import LossReportQuery
from apps.reports.queries.margin_report import MarginReportQuery
from apps.reports.queries.purchase_report import PurchaseReportQuery
from apps.reports.queries.sales_report import SalesReportQuery
from apps.reports.queries.shareholder_statement import ShareholderStatementQuery
from apps.reports.queries.supplier_outstanding_report import SupplierOutstandingReportQuery
from apps.reports.queries.supplier_statement import SupplierStatementQuery
from apps.reports.queries.transporter_outstanding_report import TransporterOutstandingReportQuery
from apps.reports.queries.transporter_statement import TransporterStatementQuery
from apps.reports.queries.treasury_statement import TreasuryStatementQuery
from apps.reports.queries.trip_fee_debt_report import TripFeeDebtReportQuery
from apps.reports.queries.trip_report import TripReportQuery
from apps.reports.queries.truck_history import TruckHistoryQuery
from apps.reports.serialization import decimals_to_str
from apps.reports.services.report_document import build_report_document
from apps.reports.services.report_pdf import render_report_pdf

# The 16 V1 report types from ERP_Specification.md Section 37. Bank
# statement/cash statement are one TreasuryStatementQuery implementation
# parametrised by which account kwarg is passed, registered under both
# spec-named slugs so the API surface still exposes 16 addressable types.
REPORT_REGISTRY = {
    "customer-statement": CustomerStatementQuery,
    "supplier-statement": SupplierStatementQuery,
    "transporter-statement": TransporterStatementQuery,
    "truck-history": TruckHistoryQuery,
    "trip-report": TripReportQuery,
    "purchase-report": PurchaseReportQuery,
    "sales-report": SalesReportQuery,
    "expense-report": ExpenseReportQuery,
    "customer-outstanding": CustomerOutstandingReportQuery,
    "supplier-outstanding": SupplierOutstandingReportQuery,
    "transporter-outstanding": TransporterOutstandingReportQuery,
    "fuel-stock": FuelStockReportQuery,
    "loss-report": LossReportQuery,
    "margin-report": MarginReportQuery,
    "bank-statement": TreasuryStatementQuery,
    "cash-statement": TreasuryStatementQuery,
    "shareholder-statement": ShareholderStatementQuery,
    "capital-report": CapitalReportQuery,
    "general-expense-report": GeneralExpenseReportQuery,
    "trip-fee-debt-report": TripFeeDebtReportQuery,
    "general-debt-report": GeneralDebtReportQuery,
    "general-receivable-report": GeneralReceivableReportQuery,
}

_EXPORT_CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _user_can_export(user) -> bool:
    if user.is_superuser:
        return True
    return bool(user.role and user.role.has_permission("reports", "export"))


class ReportViewSet(viewsets.ViewSet):
    """GET /api/reports/{report_type}/ - routes to the matching
    apps.reports.queries.* class; `?export=csv|xlsx` streams the same rows
    as a file download instead of JSON."""

    permission_classes = [HasModulePermission]
    module = "reports"

    def retrieve(self, request, pk=None):
        query_class = REPORT_REGISTRY.get(pk)
        if query_class is None:
            raise NotFound(f"Type de rapport inconnu : '{pk}'.")

        # request.query_params carries the same "?range=|&from=&to=" shape
        # the dashboard endpoint accepts; resolve it to date_from/date_to
        # here since query_class.run() only knows that pair, not "range".
        params = {
            key: value
            for key, value in request.query_params.items()
            if key
            not in {
                "export",
                "document",
                "lang",
                "preset",
                "range",
                "start_date",
                "end_date",
                "from",
                "to",
                "start",
                "end",
            }
        }
        date_from, date_to = resolve_date_range(request.query_params)
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        try:
            rows = query_class.run(**params)
        except (TypeError, ValueError) as exc:
            # TypeError: a required filter (e.g. customer_id) is missing;
            # ValueError: a malformed id ("abc") - both are client errors.
            raise ValidationError(str(exc))
        except ObjectDoesNotExist:
            # e.g. an unknown bank/cash account id on a treasury statement.
            raise NotFound("Entité introuvable pour ce rapport.")

        export_format = request.query_params.get("export")
        if export_format:
            return self._export(pk, query_class, rows, export_format, request, params)

        payload = {"report_type": pk, "fields": query_class.FIELDS, "rows": rows}
        if request.query_params.get("document") in ("1", "true"):
            payload["document"] = self._document(pk, query_class, rows, params, request)
        return Response(decimals_to_str(payload))

    @classmethod
    def _document(cls, report_type, query_class, rows, params, request):
        return build_report_document(
            report_type,
            rows,
            params,
            request.query_params.get("lang", "fr"),
            statement_context=cls._statement_context(query_class, params),
        )

    @staticmethod
    def _statement_context(query_class, params):
        """Opening/closing figures computed by the business query itself
        (spec D4/D5) - only statements define them."""
        if hasattr(query_class, "statement_context"):
            return query_class.statement_context(**params)
        if hasattr(query_class, "opening_balance"):
            return {"opening_balance": query_class.opening_balance(**params)}
        return None

    def _export(self, report_type, query_class, rows, export_format, request, params):
        if not _user_can_export(request.user):
            raise PermissionDenied("Export non autorise pour ce role.")
        if export_format not in _EXPORT_CONTENT_TYPES:
            raise NotFound(f"Format d'export inconnu : '{export_format}'.")

        if export_format == "csv":
            content = rows_to_csv(query_class.FIELDS, rows)
        elif export_format == "xlsx":
            content = rows_to_xlsx(query_class.FIELDS, rows)
        else:
            document = self._document(report_type, query_class, rows, params, request)
            content = render_report_pdf(document, rows)
        response = HttpResponse(content, content_type=_EXPORT_CONTENT_TYPES[export_format])
        response["Content-Disposition"] = f'attachment; filename="{report_type}.{export_format}"'
        return response
