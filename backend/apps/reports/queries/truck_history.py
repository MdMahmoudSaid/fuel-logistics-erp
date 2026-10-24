# TruckHistoryQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7).

from apps.reports.services.profit import TripProfitService
from apps.trips.models import Trip

FIELDS = ["trip_reference", "loading_date", "status", "quantity_loaded", "client", "current_margin"]


class TruckHistoryQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, truck_id=None, date_from=None, date_to=None) -> list[dict]:
        trips = Trip.objects.select_related("truck").order_by("-loading_date", "-id")
        if truck_id not in (None, ""):
            trips = trips.filter(truck_id=truck_id)
            with_truck = False
        else:  # no truck picked: every truck, each line names its truck
            with_truck = True
        if date_from:
            trips = trips.filter(loading_date__gte=date_from)
        if date_to:
            trips = trips.filter(loading_date__lte=date_to)

        rows = []
        for trip in trips:
            sale = getattr(trip, "sale", None)
            rows.append(
                {
                    **({"truck": trip.truck.internal_id} if with_truck else {}),
                    "trip_reference": trip.reference,
                    "loading_date": trip.loading_date,
                    "status": trip.status,
                    "quantity_loaded": trip.quantity_loaded,
                    "client": sale.customer.name if sale else (trip.client.name if trip.client_id else None),
                    "current_margin": (
                        TripProfitService.calculate_current_margin(trip) if sale else None
                    ),
                }
            )
        return rows
