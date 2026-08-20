# SearchView - global search (docs/PHASE_6_PLAN.md Etape 5;
# ERP_Implementation_Experience_Guide.md Section 9.8).
#
# icontains across indexed columns for V1, per the guide: "Start with
# indexed columns ... Do not add Elasticsearch/OpenSearch in V1 without
# evidence it is necessary."

from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasModulePermission
from apps.customers.models import Customer
from apps.purchasing.models import CessionLetter
from apps.reports.serialization import decimals_to_str
from apps.sales.models import CustomerOrder, Invoice
from apps.suppliers.models import Supplier
from apps.transport.models import Transporter, Truck
from apps.trips.models import Trip

_RESULT_LIMIT = 20


class SearchView(APIView):
    permission_classes = [HasModulePermission]
    module = "reports"
    # HasModulePermission reads `view.action` (a ViewSet concept) to map onto
    # a permission-matrix action; a plain APIView has no such attribute, so
    # this is fixed to "view" - the only tier a read-only search needs.
    action = "view"

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response(self._empty_results())

        return Response(
            decimals_to_str(
                {
                    "trucks": self._search_trucks(query),
                    "customers": list(
                        Customer.objects.filter(name__icontains=query).values("id", "name")[
                            :_RESULT_LIMIT
                        ]
                    ),
                    "suppliers": list(
                        Supplier.objects.filter(name__icontains=query).values("id", "name")[
                            :_RESULT_LIMIT
                        ]
                    ),
                    "transporters": list(
                        Transporter.objects.filter(name__icontains=query).values("id", "name")[
                            :_RESULT_LIMIT
                        ]
                    ),
                    "trips": self._search_trips(query),
                    "invoices": list(
                        Invoice.objects.filter(invoice_number__icontains=query).values(
                            "id", "invoice_number", "status"
                        )[:_RESULT_LIMIT]
                    ),
                    "orders": self._search_orders(query),
                    "cessions": list(
                        CessionLetter.objects.filter(reference__icontains=query).values(
                            "id", "reference", "status"
                        )[:_RESULT_LIMIT]
                    ),
                }
            )
        )

    @staticmethod
    def _empty_results():
        return {
            "trucks": [],
            "customers": [],
            "suppliers": [],
            "transporters": [],
            "trips": [],
            "invoices": [],
            "orders": [],
            "cessions": [],
        }

    @staticmethod
    def _search_trucks(query):
        trucks = Truck.objects.filter(
            Q(internal_id__icontains=query)
            | Q(tractor_registration__icontains=query)
            | Q(tanker_registration__icontains=query)
        )[:_RESULT_LIMIT]

        results = []
        for truck in trucks:
            active_trip = (
                truck.trips.exclude(status__in=Trip.TERMINAL_STATUSES)
                .select_related("product", "client", "sale", "sale__customer")
                .order_by("-loading_date", "-id")
                .first()
            )
            current_trip = None
            if active_trip is not None:
                sale = getattr(active_trip, "sale", None)
                current_trip = {
                    "reference": active_trip.reference,
                    "status": active_trip.status,
                    "product": active_trip.product.name,
                    "quantity_loaded": active_trip.quantity_loaded,
                    "client": (
                        sale.customer.name
                        if sale
                        else (active_trip.client.name if active_trip.client_id else None)
                    ),
                }
            results.append(
                {
                    "id": truck.id,
                    "internal_id": truck.internal_id,
                    "tractor_registration": truck.tractor_registration,
                    "tanker_registration": truck.tanker_registration,
                    "current_trip": current_trip,
                }
            )
        return results

    @staticmethod
    def _search_trips(query):
        trips = Trip.objects.filter(
            Q(reference__icontains=query) | Q(bl_reference__icontains=query)
        ).select_related("product")[:_RESULT_LIMIT]
        return [
            {"id": trip.id, "reference": trip.reference, "status": trip.status, "product": trip.product.name}
            for trip in trips
        ]

    @staticmethod
    def _search_orders(query):
        if not query.isdigit():
            return []
        return list(
            CustomerOrder.objects.filter(id=int(query)).values("id", "status", "quantity_ordered")
        )
