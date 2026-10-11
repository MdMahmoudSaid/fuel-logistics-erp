from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.core.reference import generate_monthly_reference

from .models import Quotation, QuotationLine
from .serializers import QuotationSerializer

_MAX_REFERENCE_ATTEMPTS = 5
_REFERENCE_PREFIX = "PF"  # proforma; older DEV-... references stay valid


def _next_reference() -> str:
    return generate_monthly_reference(Quotation, "reference", _REFERENCE_PREFIX)


class QuotationViewSet(viewsets.ModelViewSet):
    queryset = (
        Quotation.objects.select_related("customer", "created_by")
        .prefetch_related("lines", "lines__product")
        .all()
    )
    serializer_class = QuotationSerializer
    filterset_fields = ["customer", "status"]
    permission_classes = [HasModulePermission]
    module = "sales"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = _next_reference()
            try:
                with transaction.atomic():
                    serializer.save(reference=reference, created_by=self.request.user)
                return
            except IntegrityError:
                continue
        raise IntegrityError(
            "Impossible de generer une reference de devis unique apres "
            f"{_MAX_REFERENCE_ATTEMPTS} tentatives."
        )

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """Copy an existing quotation (lines included) into a fresh DRAFT
        with a new reference - "create/save/edit/duplicate/preview/print/
        PDF" (product decision 2026-09-05). Never copies status as-is: a
        duplicate always starts DRAFT, regardless of the source's status.

        POST /api/quotations/{id}/duplicate/
        """
        original = self.get_object()
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            reference = _next_reference()
            try:
                with transaction.atomic():
                    copy = Quotation.objects.create(
                        reference=reference,
                        customer=original.customer,
                        customer_name=original.customer_name,
                        status=Quotation.Status.DRAFT,
                        issue_date=timezone.localdate(),
                        validity_date=original.validity_date,
                        currency=original.currency,
                        notes=original.notes,
                        payment_terms=original.payment_terms,
                        show_bank_accounts=original.show_bank_accounts,
                        created_by=request.user,
                    )
                    for line in original.lines.all():
                        QuotationLine.objects.create(
                            quotation=copy,
                            product=line.product,
                            description=line.description,
                            quantity=line.quantity,
                            unit=line.unit,
                            unit_price=line.unit_price,
                        )
                    total = (
                        copy.lines.aggregate(total=Sum("line_total"))["total"] or Decimal("0.00")
                    )
                    copy.total_amount = total
                    copy.save(update_fields=["total_amount"])
                break
            except IntegrityError:
                continue
        else:
            raise IntegrityError(
                "Impossible de generer une reference de devis unique apres "
                f"{_MAX_REFERENCE_ATTEMPTS} tentatives."
            )
        return Response(
            QuotationSerializer(copy, context={"request": request}).data, status=201
        )

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        """GET /api/quotations/{id}/pdf/?lang=fr|en|ar"""
        from apps.reports.services.proforma_pdf import render_proforma_pdf

        quotation = self.get_object()
        lang = request.query_params.get("lang", "fr")
        pdf_bytes = render_proforma_pdf(quotation, lang=lang)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="proforma-{quotation.reference}.pdf"'
        )
        return response
