# TransporterOutstandingReportQuery - "transporter outstanding report"
# (ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md Etape 4/6).
#
# "Outstanding" per transporter is net_amount minus whatever has actually
# been disbursed against each settlement via the TreasuryTransaction ledger
# (ControlledDebtPaymentService._paid_for_source) - the same reste-a-payer
# figure shown on the "Nouveau paiement" screen
# (ControlledDebtPaymentService.describe_transporter), so this report and
# the payment screen never disagree.

from decimal import Decimal

from apps.core.request_cache import memoize_per_request
from apps.finance.models import OpeningDebt, TransportPayment
from apps.finance.services import ControlledDebtPaymentService
from apps.transport.models import Transporter

FIELDS = ["transporter", "outstanding"]
ZERO = Decimal("0.00")


class TransporterOutstandingReportQuery:
    FIELDS = FIELDS

    @classmethod
    @memoize_per_request
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        # "As of today" report: the period params are accepted and ignored
        # (the Reports page hides the period filter for it; a direct call with
        # dates must not fail).
        transporter_ids = set(
            TransportPayment.objects.exclude(status=TransportPayment.Status.PAID)
            .values_list("transporter_id", flat=True)
        ) | set(
            OpeningDebt.objects.filter(cancelled_at__isnull=True, transporter__isnull=False)
            .values_list("transporter_id", flat=True)
        )
        rows = []
        for transporter in Transporter.objects.filter(id__in=transporter_ids):
            outstanding = ControlledDebtPaymentService.describe_transporter(transporter)[
                "remaining_amount"
            ]
            if outstanding > ZERO:
                rows.append({"transporter": transporter.name, "outstanding": outstanding})
        return rows
