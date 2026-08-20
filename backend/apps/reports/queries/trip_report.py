# TripReportQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from apps.trips.models import Trip

FIELDS = [
    "trip_reference",
    "loading_date",
    "status",
    "truck",
    "transporter",
    "supplier",
    "product",
    "quantity_loaded",
    "client",
]


class TripReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, status=None, date_from=None, date_to=None) -> list[dict]:
        trips = Trip.objects.select_related(
            "truck", "transporter", "supplier", "product", "client"
        ).order_by("-loading_date", "-id")
        if status:
            trips = trips.filter(status=status)
        if date_from:
            trips = trips.filter(loading_date__gte=date_from)
        if date_to:
            trips = trips.filter(loading_date__lte=date_to)

        return [
            {
                "trip_reference": trip.reference,
                "loading_date": trip.loading_date,
                "status": trip.status,
                "truck": trip.truck.internal_id,
                "transporter": trip.transporter.name,
                "supplier": trip.supplier.name,
                "product": trip.product.name,
                "quantity_loaded": trip.quantity_loaded,
                "client": trip.client.name if trip.client_id else None,
            }
            for trip in trips
        ]
