import datetime

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.services.ledger_pdf import DEFAULT_COMPANY_NAME, render_ledger_pdf

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "sales"

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Customer account statement: invoices, payments received and the
        outstanding receivable balance (docs/PHASE_5_PLAN.md Etape 8;
        guide Section 8.3/8.4).

        GET /api/customers/{id}/ledger/
        """
        # Imported lazily: apps.customers sits below apps.sales/apps.finance
        # in the app dependency graph (both already import
        # apps.customers.serializers.CustomerSerializer), so a module-level
        # import here would run the dependency the wrong way round.
        from apps.finance.serializers import CustomerPaymentSerializer
        from apps.finance.services import PaymentAllocationService
        from apps.sales.models import Invoice
        from apps.sales.serializers import InvoiceSerializer

        customer = self.get_object()
        invoices = Invoice.objects.filter(sale__customer=customer).select_related(
            "sale", "sale__customer"
        )
        payments = customer.payments.select_related(
            "bank_account", "cash_account", "recorded_by"
        ).prefetch_related("allocations")

        invoices_data = []
        for invoice in invoices:
            row = InvoiceSerializer(invoice, context={"request": request}).data
            row["outstanding"] = f"{PaymentAllocationService.get_invoice_outstanding(invoice):.2f}"
            invoices_data.append(row)

        outstanding_balance = PaymentAllocationService.get_customer_outstanding(customer)

        return Response(
            {
                "customer": CustomerSerializer(customer).data,
                "outstanding_balance": f"{outstanding_balance:.2f}",
                "invoices": invoices_data,
                "payments": CustomerPaymentSerializer(payments, many=True, context={"request": request}).data,
            }
        )

    @action(detail=True, methods=["get"], url_path="ledger/pdf")
    def ledger_pdf(self, request, pk=None):
        """PDF export of the customer ledger (Task 10) - a dedicated action
        rather than a `?format=pdf` query param on `ledger` above: DRF's
        DefaultContentNegotiation reserves the `format` query parameter for
        its own renderer selection and raises Http404 before the view is
        even called when the value doesn't match a registered renderer
        (verified while implementing this task) - the same reason
        apps/reports/views/reports.py's export branch uses `?export=`
        instead of `?format=`. Spec Section 5 explicitly allows this
        "action dediee /pdf/" alternative.

        This endpoint's JSON shape (customer/outstanding_balance/invoices/
        payments) is very different from the supplier/transporter ledger
        dicts, so it's adapted here into the generic (summary dict, rows
        list) render_ledger_pdf signature rather than special-cased inside
        the renderer - no new calculation, just the existing invoice/
        payment field values reduced to a common printable shape (type/
        date/reference/amount/status), the same "entries" shape
        SupplierLedgerService/TransporterLedgerService already use.

        GET /api/customers/{id}/ledger/pdf/?lang=fr|en|ar
        """
        from apps.finance.services import PaymentAllocationService
        from apps.sales.models import Invoice

        customer = self.get_object()
        invoices = Invoice.objects.filter(sale__customer=customer).select_related("sale")
        payments = customer.payments.all()
        outstanding_balance = PaymentAllocationService.get_customer_outstanding(customer)
        lang = request.query_params.get("lang", "fr")

        rows = [
            {
                "date": invoice.issued_date,
                "type": "invoice",
                "reference": invoice.invoice_number,
                "amount": invoice.total_amount,
                "status": invoice.status,
            }
            for invoice in invoices
        ] + [
            {
                "date": payment.payment_date,
                "type": "payment",
                "reference": payment.reference,
                "amount": payment.amount,
                "status": payment.method,
            }
            for payment in payments
        ]
        rows.sort(key=lambda row: row["date"])

        pdf_bytes = render_ledger_pdf(
            company_name=DEFAULT_COMPANY_NAME,
            account_type="client",
            party_name=customer.name,
            export_date=datetime.date.today(),
            summary={"outstanding_balance": outstanding_balance},
            rows=rows,
            lang=lang,
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="grand-livre-{customer.name}.pdf"'
        return response
