import importlib

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasModulePermission
from apps.core.reference import generate_monthly_reference
from apps.trips.models import Trip

from .models import DeliveryNote, DeliveryNoteLine, LoadingSheet, PurchaseOrderDocument
from .serializers import DeliveryNoteSerializer, LoadingSheetSerializer, PurchaseOrderDocumentSerializer

_MAX_REFERENCE_ATTEMPTS = 5


class BaseDocumentViewSet(viewsets.ModelViewSet):
    """Auto reference (PREFIX-YYYYMM-NNNN) and GET .../{id}/pdf/?lang= for
    every commercial document. Subclasses set module, prefix, pdf_builder
    ("module.path:function") and filename."""

    permission_classes = [HasModulePermission]
    prefix = ""
    pdf_builder = ""
    filename = ""

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        model = serializer.Meta.model
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            try:
                with transaction.atomic():
                    serializer.save(
                        reference=generate_monthly_reference(model, "reference", self.prefix),
                        created_by=self.request.user,
                    )
                return
            except IntegrityError:
                continue
        raise IntegrityError("Impossible de generer une reference unique.")

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        module_path, function = self.pdf_builder.split(":")
        render = getattr(importlib.import_module(module_path), function)
        document = self.get_object()
        response = HttpResponse(
            render(document, request.query_params.get("lang", "fr")), content_type="application/pdf"
        )
        response["Content-Disposition"] = f'attachment; filename="{self.filename}-{document.reference}.pdf"'
        return response


class DeliveryNoteViewSet(BaseDocumentViewSet):
    queryset = DeliveryNote.objects.select_related("customer").prefetch_related("lines")
    serializer_class = DeliveryNoteSerializer
    filterset_fields = ["customer"]
    module = "sales"
    prefix = "BL"
    pdf_builder = "apps.reports.services.document_pdfs:render_delivery_note_pdf"
    filename = "bon-livraison"

    @action(detail=False, methods=["get"], url_path="deliverable-trips")
    def deliverable_trips(self, request):
        """The customer's delivered trips, each pre-filled as a line, with the
        delivery notes it already appears on (a warning, never a block)."""
        trips = list(
            Trip.objects.filter(
                client_id=request.query_params.get("customer"),
                status__in=[Trip.Status.DELIVERED, Trip.Status.COMPLETED],
            )
            .select_related("truck", "product", "delivery_control")
            .order_by("-loading_date", "-id")
        )
        notes: dict[int, list[str]] = {}
        for trip_id, reference in DeliveryNoteLine.objects.filter(
            trip_id__in=[t.id for t in trips]
        ).values_list("trip_id", "note__reference").distinct():
            notes.setdefault(trip_id, []).append(reference)
        data = []
        for trip in trips:
            line = DeliveryNoteLine.from_trip(trip)
            data.append({
                **line,
                "quantity": f"{line['quantity']:.2f}",
                "missing": None if line["missing"] is None else f"{line['missing']:.2f}",
                "reference": trip.reference,
                "loading_date": trip.loading_date,
                "truck": trip.truck.internal_id,
                "other_notes": sorted(notes.get(trip.id, [])),
            })
        return Response(data)


class LoadingSheetViewSet(BaseDocumentViewSet):
    queryset = LoadingSheet.objects.select_related("supplier").prefetch_related("lines")
    serializer_class = LoadingSheetSerializer
    filterset_fields = ["supplier"]
    module = "purchasing"
    prefix = "BCH"
    pdf_builder = "apps.reports.services.document_pdfs:render_loading_sheet_pdf"
    filename = "bon-chargement"


class PurchaseOrderDocumentViewSet(BaseDocumentViewSet):
    queryset = PurchaseOrderDocument.objects.select_related("supplier").prefetch_related("lines")
    serializer_class = PurchaseOrderDocumentSerializer
    filterset_fields = ["supplier", "status"]
    module = "purchasing"
    prefix = "BCF"
    pdf_builder = "apps.reports.services.document_pdfs:render_purchase_order_pdf"
    filename = "bon-commande"
