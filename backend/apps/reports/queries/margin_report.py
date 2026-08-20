# MarginReportQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.1/9.7).
#
# One row per trip that has produced a Sale, delegating the actual number
# to TripProfitService so this never duplicates the margin formula (guide
# Section 9.1: "do not scatter profitability formulas throughout
# serializers and dashboard queries").

from apps.reports.services.profit import TripProfitService
from apps.trips.models import Trip

FIELDS = ["trip_reference", "client", "product", "current_margin"]


class MarginReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        trips = Trip.objects.filter(sale__isnull=False).select_related(
            "sale", "sale__customer", "product"
        ).order_by("-loading_date", "-id")
        if date_from:
            trips = trips.filter(loading_date__gte=date_from)
        if date_to:
            trips = trips.filter(loading_date__lte=date_to)

        return [
            {
                "trip_reference": trip.reference,
                "client": trip.sale.customer.name,
                "product": trip.product.name,
                "current_margin": TripProfitService.calculate_current_margin(trip),
            }
            for trip in trips
        ]
