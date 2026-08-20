# TransporterOutstandingReportQuery - "transporter outstanding report"
# (ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md Etape 4/6).
#
# Unlike customer/supplier outstanding, there is no separate "amount
# actually disbursed" ledger for transporters - TransportPayment.net_amount
# already is the final computed liability per settlement, and its `status`
# tracks payment progress (guide Section 1.5/8.6). So "outstanding" here is
# the sum of net_amount on settlements not yet fully PAID, per transporter.

from decimal import Decimal

from django.db.models import Sum

from apps.finance.models import TransportPayment
from apps.transport.models import Transporter

FIELDS = ["transporter", "outstanding"]
ZERO = Decimal("0.00")


class TransporterOutstandingReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls) -> list[dict]:
        transporter_ids = (
            TransportPayment.objects.exclude(status=TransportPayment.Status.PAID)
            .values_list("transporter_id", flat=True)
            .distinct()
        )
        rows = []
        for transporter in Transporter.objects.filter(id__in=transporter_ids):
            outstanding = (
                TransportPayment.objects.filter(transporter=transporter)
                .exclude(status=TransportPayment.Status.PAID)
                .aggregate(total=Sum("net_amount"))["total"]
                or ZERO
            )
            rows.append({"transporter": transporter.name, "outstanding": outstanding})
        return rows
