# TransporterStatementQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7/1.5).
#
# One row per settled trip: TransportPayment already nets deduction_amount
# and any advance consumed into net_amount at settlement time (guide
# Section 1.5's "earned - deductions - advances - payments = outstanding"),
# so this lists that breakdown per trip rather than re-deriving it from
# TransportDeduction/TransporterAdvance separately.

from apps.finance.models import TransportPayment

FIELDS = ["date", "trip_reference", "base_amount", "deduction_amount", "advance_applied", "net_amount"]


class TransporterStatementQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, transporter_id, date_from=None, date_to=None) -> list[dict]:
        payments = TransportPayment.objects.filter(
            transporter_id=transporter_id
        ).select_related("trip").order_by("created_at", "id")
        if date_from:
            payments = payments.filter(created_at__date__gte=date_from)
        if date_to:
            payments = payments.filter(created_at__date__lte=date_to)

        return [
            {
                "date": payment.created_at.date(),
                "trip_reference": payment.trip.reference,
                "base_amount": payment.base_amount,
                "deduction_amount": payment.deduction_amount,
                "advance_applied": (
                    payment.advance_applied.amount if payment.advance_applied_id else 0
                ),
                "net_amount": payment.net_amount,
            }
            for payment in payments
        ]
