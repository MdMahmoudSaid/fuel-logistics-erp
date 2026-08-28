# ReportViewSet (docs/PHASE_6_PLAN.md Etape 5;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.date_range import resolve_date_range
from apps.reports.export import rows_to_csv, rows_to_pdf, rows_to_xlsx
from apps.reports.queries.customer_outstanding_report import CustomerOutstandingReportQuery
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.expense_report import ExpenseReportQuery
from apps.reports.queries.fuel_stock_report import FuelStockReportQuery
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
from apps.reports.queries.trip_report import TripReportQuery
from apps.reports.queries.truck_history import TruckHistoryQuery
from apps.reports.serialization import decimals_to_str

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
            if key not in {"export", "range", "from", "to"}
        }
        date_from, date_to = resolve_date_range(request.query_params)
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        try:
            rows = query_class.run(**params)
        except TypeError as exc:
            raise ValidationError(str(exc))

        export_format = request.query_params.get("export")
        if export_format:
            return self._export(pk, query_class, rows, export_format, request.user)

        return Response(
            decimals_to_str({"report_type": pk, "fields": query_class.FIELDS, "rows": rows})
        )

    def _export(self, report_type, query_class, rows, export_format, user):
        if not _user_can_export(user):
            raise PermissionDenied("Export non autorise pour ce role.")
        if export_format not in _EXPORT_CONTENT_TYPES:
            raise NotFound(f"Format d'export inconnu : '{export_format}'.")

        if export_format == "csv":
            content = rows_to_csv(query_class.FIELDS, rows)
        elif export_format == "xlsx":
            content = rows_to_xlsx(query_class.FIELDS, rows)
        else:
            content = rows_to_pdf(query_class.FIELDS, rows, title=report_type)
        response = HttpResponse(content, content_type=_EXPORT_CONTENT_TYPES[export_format])
        response["Content-Disposition"] = f'attachment; filename="{report_type}.{export_format}"'
        return response
