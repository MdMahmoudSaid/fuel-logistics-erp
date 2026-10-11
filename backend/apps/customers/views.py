import datetime
from decimal import Decimal

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.reports.services.ledger_pdf import (
    DEFAULT_COMPANY_NAME,
    get_ledger_pdf_labels,
    render_ledger_pdf,
)

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
        from apps.finance.serializers import CustomerPaymentSerializer, OpeningDebtSerializer
        from apps.finance.services import OpeningDebtService, PaymentAllocationService
        from apps.sales.models import Invoice
        from apps.sales.serializers import InvoiceSerializer

        customer = self.get_object()
        invoices = Invoice.objects.filter(sale__customer=customer).select_related(
            "sale", "sale__customer", "sale__trip", "sale__trip__truck"
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
                "available_credit": (
                    f"{PaymentAllocationService.get_customer_available_credit(customer):.2f}"
                ),
                "invoices": invoices_data,
                "opening_debts": OpeningDebtSerializer(
                    OpeningDebtService.active(customer=customer), many=True, context={"request": request}
                ).data,
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

        Section 3 (recette corrections 2026-09-05): the summary and the
        extra "Liste des factures"/"Liste des paiements" sections mirror
        CustomerLedgerView.vue's own totalInvoiced/totalReceived/
        openInvoices/lastPayment computations exactly (same fields, same
        sums) so this export can never disagree with what the page shows -
        no new calculation invented for the PDF, just the same numbers the
        page already displays, reduced to a printable shape. The merged
        chronological `rows` (unchanged from the original pass) stays the
        "Historique complet" section.
        """
        from apps.finance.services import PaymentAllocationService
        from apps.sales.models import Invoice

        customer = self.get_object()
        invoices = list(Invoice.objects.filter(sale__customer=customer).select_related("sale__trip"))
        payments = list(customer.payments.all())
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
                "reference": payment.reference or f"PAY-{payment.id}",
                "amount": payment.amount,
                "status": payment.method,
            }
            for payment in payments
        ]
        rows.sort(key=lambda row: row["date"])

        total_invoiced = sum((invoice.total_amount for invoice in invoices), Decimal("0.00"))
        total_received = sum((payment.amount for payment in payments), Decimal("0.00"))
        open_invoices = [
            invoice
            for invoice in invoices
            if PaymentAllocationService.get_invoice_outstanding(invoice) > 0
            and invoice.status != Invoice.Status.CANCELLED
        ]
        last_payment = max(payments, key=lambda p: p.payment_date, default=None)

        invoices_section = [
            {
                "invoice_number": invoice.invoice_number,
                "issued_date": invoice.issued_date,
                "quantity_loaded": sum((x.trip.quantity_loaded for x in invoice.all_sales), Decimal("0.00")),
                "delivered_quantity": sum((x.delivered_quantity for x in invoice.all_sales), Decimal("0.00")),
                "total_amount": invoice.total_amount,
                "outstanding": PaymentAllocationService.get_invoice_outstanding(invoice),
                "status": invoice.status,
            }
            for invoice in invoices
        ]
        payments_section = [
            {
                "payment_date": payment.payment_date,
                "method": payment.method,
                "reference": payment.reference or f"PAY-{payment.id}",
                "amount": payment.amount,
            }
            for payment in payments
        ]

        pdf_bytes = render_ledger_pdf(
            company_name=DEFAULT_COMPANY_NAME,
            account_type="client",
            party_name=customer.name,
            export_date=datetime.date.today(),
            summary={
                "total_invoiced": total_invoiced,
                "total_received": total_received,
                "outstanding_balance": outstanding_balance,
                "open_invoices": len(open_invoices),
                "last_payment": last_payment.amount if last_payment else None,
            },
            rows=rows,
            lang=lang,
            extra_sections=[
                {"title": get_ledger_pdf_labels(lang)["invoices_section"], "rows": invoices_section},
                {"title": get_ledger_pdf_labels(lang)["payments_section"], "rows": payments_section},
            ],
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="grand-livre-{customer.name}.pdf"'
        return response
