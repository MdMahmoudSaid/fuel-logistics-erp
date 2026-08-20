# LossReportQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7/7.3/7.4).

from apps.trips.models import DeliveryControl

FIELDS = [
    "trip_reference",
    "control_date",
    "loaded_quantity",
    "received_quantity",
    "loss_quantity",
    "tolerance_quantity",
    "chargeable_loss_quantity",
]


class LossReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        controls = DeliveryControl.objects.select_related("trip").order_by(
            "-control_date", "-id"
        )
        if date_from:
            controls = controls.filter(control_date__gte=date_from)
        if date_to:
            controls = controls.filter(control_date__lte=date_to)

        return [
            {
                "trip_reference": control.trip.reference,
                "control_date": control.control_date,
                "loaded_quantity": control.loaded_quantity,
                "received_quantity": control.received_quantity,
                "loss_quantity": control.loss_quantity,
                "tolerance_quantity": control.tolerance_quantity,
                "chargeable_loss_quantity": control.chargeable_loss_quantity,
            }
            for control in controls
        ]
