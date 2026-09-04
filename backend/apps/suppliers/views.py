import datetime
from decimal import Decimal

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.serialization import decimals_to_str
from apps.reports.services.ledger_pdf import DEFAULT_COMPANY_NAME, render_ledger_pdf

from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    filterset_fields = ["is_active", "country"]
    permission_classes = [HasModulePermission]
    module = "purchasing"

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Endpoint to get supplier purchase ledger.

        GET /api/suppliers/{id}/ledger/
        """
        supplier = self.get_object()
        from apps.purchasing.models import SupplierOrder
        from apps.purchasing.serializers import SupplierOrderSerializer
        from apps.purchasing.services import SupplierStockService

        orders = SupplierOrder.objects.filter(supplier=supplier)
        confirmed_orders = orders.filter(status=SupplierOrder.Status.CONFIRMED)
        orders_serialized = SupplierOrderSerializer(orders, many=True).data

        # Agrégation du reliquat par produit
        product_reliquats = {}
        for order in confirmed_orders:
            product_id = order.product.id
            product_name = order.product.name
            reliquat = SupplierStockService.get_purchase_reliquat(order)

            if product_id not in product_reliquats:
                product_reliquats[product_id] = {
                    "product_id": product_id,
                    "product_name": product_name,
                    "total_reliquat": Decimal("0.00"),
                }
            product_reliquats[product_id]["total_reliquat"] += reliquat

        reliquat_summary = []
        for item in product_reliquats.values():
            reliquat_summary.append(
                {
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "total_reliquat": f"{item['total_reliquat']:.2f}",
                }
            )

        # Imported lazily: apps.suppliers sits below apps.finance in the app
        # dependency graph (apps.finance.models references
        # "suppliers.Supplier" only via string FK), so a module-level import
        # here would run the dependency the wrong way round
        # (docs/PHASE_5_PLAN.md Etape 8: "achats + acomptes/avances fournisseurs").
        from apps.finance.serializers import SupplierPaymentSerializer
        from apps.finance.services import SupplierLedgerService

        ledger_data = SupplierLedgerService.get_ledger(supplier)

        payments = supplier.payments.select_related(
            "supplier_order", "bank_account", "cash_account", "recorded_by"
        )
        total_paid = sum((p.amount for p in payments), Decimal("0.00"))
        total_purchased = sum((o.total_amount for o in confirmed_orders), Decimal("0.00"))

        return Response(
            {
                "supplier": {
                    "id": supplier.id,
                    "name": supplier.name,
                },
                "orders": orders_serialized,
                "reliquat_summary": reliquat_summary,
                "payments": SupplierPaymentSerializer(
                    payments, many=True, context={"request": request}
                ).data,
                "total_purchased": f"{total_purchased:.2f}",
                "total_paid": f"{total_paid:.2f}",
                "outstanding_balance": f"{total_purchased - total_paid:.2f}",
                "summary": decimals_to_str(ledger_data["summary"]),
                "entries": decimals_to_str(ledger_data["entries"]),
            }
        )

    @action(detail=True, methods=["get"], url_path="ledger/pdf")
    def ledger_pdf(self, request, pk=None):
        """PDF export of the supplier ledger (Task 10) - a dedicated action
        rather than a `?format=pdf` query param on `ledger` above: DRF's
        DefaultContentNegotiation reserves the `format` query parameter for
        its own renderer selection and raises Http404 before the view is
        even called when the value doesn't match a registered renderer
        (verified while implementing this task) - the same reason
        apps/reports/views/reports.py's export branch uses `?export=`
        instead of `?format=`. Spec Section 5 explicitly allows this
        "action dediee /pdf/" alternative. Prints the same
        SupplierLedgerService.get_ledger() dict as `ledger` above - no new
        calculation.

        GET /api/suppliers/{id}/ledger/pdf/?lang=fr|en|ar
        """
        supplier = self.get_object()

        from apps.finance.services import SupplierLedgerService

        ledger_data = SupplierLedgerService.get_ledger(supplier)
        lang = request.query_params.get("lang", "fr")
        pdf_bytes = render_ledger_pdf(
            company_name=DEFAULT_COMPANY_NAME,
            account_type="fournisseur",
            party_name=supplier.name,
            export_date=datetime.date.today(),
            summary=ledger_data["summary"],
            rows=ledger_data["entries"],
            lang=lang,
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="grand-livre-{supplier.name}.pdf"'
        return response
