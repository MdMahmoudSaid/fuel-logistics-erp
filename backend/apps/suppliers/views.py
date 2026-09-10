import datetime
from decimal import Decimal

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.serialization import decimals_to_str
from apps.reports.services.ledger_pdf import (
    DEFAULT_COMPANY_NAME,
    get_ledger_pdf_labels,
    render_ledger_pdf,
)

from .models import Supplier
from .serializers import SupplierSerializer


def _reliquat_by_product(confirmed_orders) -> list[dict]:
    """Shared by `ledger` (JSON) and `ledger_pdf` (Section 3, recette
    corrections 2026-09-05) so the PDF's "Reliquat par produit" section can
    never disagree with the on-screen SupplierLedgerView.vue table - single
    computation, two consumers, same pre-existing SupplierStockService
    calculation this always used."""
    from apps.purchasing.services import SupplierStockService

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

    return list(product_reliquats.values())


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

        reliquat_summary = [
            {
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "total_reliquat": f"{item['total_reliquat']:.2f}",
            }
            for item in _reliquat_by_product(confirmed_orders)
        ]

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
        # Task 6 (client business decision, confirmed 2026-09-06): the
        # payments list itself still shows a cancelled payment (full audit
        # trail, is_reversed flag visible via the serializer) - only the
        # total must exclude it, since it never really left treasury net
        # of its own reversal.
        total_paid = sum(
            (p.amount for p in payments if not p.is_reversed), Decimal("0.00")
        )
        total_purchased = sum((o.total_amount for o in confirmed_orders), Decimal("0.00"))
        # Business rule reversal (client request, 2026-09-10): the debt owed
        # to this supplier ("outstanding_balance") is the full confirmed
        # order total, due immediately on confirmation - see
        # ControlledDebtPaymentService.describe_supplier_order
        # (apps.finance.services), which this must stay consistent with.

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
                "outstanding_balance": f"{max(total_purchased - total_paid, Decimal('0.00')):.2f}",
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

        Section 3 (recette corrections 2026-09-05): now also prints the
        "Reliquat par produit", "Historique des achats" and "Paiements et
        avances" sections already visible on SupplierLedgerView.vue,
        reusing the exact same queries/computations that view's own
        `ledger` action above already exposes - no new calculation.
        """
        from apps.purchasing.models import SupplierOrder
        from apps.finance.services import SupplierLedgerService

        supplier = self.get_object()
        lang = request.query_params.get("lang", "fr")

        ledger_data = SupplierLedgerService.get_ledger(supplier)

        confirmed_orders = SupplierOrder.objects.filter(
            supplier=supplier, status=SupplierOrder.Status.CONFIRMED
        )
        reliquat_section = [
            {"product_name": item["product_name"], "total_reliquat": item["total_reliquat"]}
            for item in _reliquat_by_product(confirmed_orders)
        ]

        all_orders = SupplierOrder.objects.filter(supplier=supplier)
        purchase_history_section = [
            {
                "reference": order.reference,
                "product": order.product.name,
                "purchase_date": order.purchase_date,
                "quantity_litres": order.quantity_litres,
                "total_amount": order.total_amount,
                "status": order.status,
            }
            for order in all_orders
        ]

        payments = supplier.payments.select_related("bank_account", "cash_account")
        payments_advances_section = [
            {
                "payment_date": payment.payment_date,
                "method": payment.method,
                "reference": payment.reference,
                "is_advance": payment.is_advance,
                "amount": payment.amount,
            }
            for payment in payments
        ]

        pdf_bytes = render_ledger_pdf(
            company_name=DEFAULT_COMPANY_NAME,
            account_type="fournisseur",
            party_name=supplier.name,
            export_date=datetime.date.today(),
            summary=ledger_data["summary"],
            rows=ledger_data["entries"],
            lang=lang,
            extra_sections=[
                {"title": get_ledger_pdf_labels(lang)["reliquat_section"], "rows": reliquat_section},
                {
                    "title": get_ledger_pdf_labels(lang)["purchase_history_section"],
                    "rows": purchase_history_section,
                },
                {
                    "title": get_ledger_pdf_labels(lang)["payments_advances_section"],
                    "rows": payments_advances_section,
                },
            ],
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="grand-livre-{supplier.name}.pdf"'
        return response
