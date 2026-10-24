# TransporterStatementQuery (docs/PHASE_6_PLAN.md Etape 4;
# ERP_Implementation_Experience_Guide.md Section 9.7/1.5).
#
# Running-balance statement, same shape as the customer/supplier statements
# (client request 2026-10-11: the relevé must follow the ledger after the
# "Nouvelle dette" / advances changes). What the company owes the
# transporter (debit): each non-cancelled trip settlement, net of its loss
# deductions, and each prior debt ("Nouvelle dette"). What reduced it
# (credit): every treasury payment made against them and every advance
# handed over. The closing balance therefore equals the ledger's
# total_due - open_advances (ControlledDebtPaymentService.
# describe_transporter_balance, net_balance with the opposite sign).

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from apps.finance.models import OpeningDebt, TransporterAdvance, TransportPayment, TreasuryTransaction
from apps.reports.queries.statement_common import entries_of, opening_balance, statement_rows

FIELDS = ["date", "type", "reference", "debit", "credit", "balance"]


class TransporterStatementQuery:
    FIELDS = FIELDS

    @staticmethod
    def _parties():
        from apps.transport.models import Transporter
        return Transporter.objects.order_by("name").values_list("id", "name")
    DIRECTION = 1  # debit - credit: a positive balance is money owed to the transporter

    @classmethod
    def _entries(cls, transporter_id) -> list[dict]:
        settlements = list(
            TransportPayment.objects.filter(transporter_id=transporter_id)
            .exclude(status=TransportPayment.Status.CANCELLED)
            .select_related("trip")
        )
        opening_debts = list(
            OpeningDebt.objects.filter(transporter_id=transporter_id, cancelled_at__isnull=True)
        )
        payments = TreasuryTransaction.objects.filter(
            Q(
                source_content_type=ContentType.objects.get_for_model(TransportPayment),
                source_object_id__in=[s.id for s in settlements],
            )
            | Q(
                source_content_type=ContentType.objects.get_for_model(OpeningDebt),
                source_object_id__in=[d.id for d in opening_debts],
            ),
            type=TreasuryTransaction.Type.MONEY_OUT,
        )
        advances = TransporterAdvance.objects.filter(transporter_id=transporter_id)
        return (
            [
                {
                    "date": debt.date,
                    "type": "OPENING_DEBT",
                    "reference": debt.reference or f"DET-{debt.id}",
                    "debit": debt.amount,
                    "credit": None,
                    "sort_key": (debt.date, -1, debt.id),
                }
                for debt in opening_debts
            ]
            + [
                {
                    "date": settlement.created_at.date(),
                    "type": "SETTLEMENT",
                    "reference": settlement.trip.reference,
                    "debit": settlement.base_amount - settlement.deduction_amount,
                    "credit": None,
                    "sort_key": (settlement.created_at.date(), 0, settlement.id),
                }
                for settlement in settlements
            ]
            + [
                {
                    "date": advance.date,
                    "type": "ADVANCE_PAID",
                    "reference": advance.reference or f"AV-{advance.id}",
                    "debit": None,
                    "credit": advance.amount,
                    "sort_key": (advance.date, 1, advance.id),
                }
                for advance in advances
            ]
            + [
                {
                    "date": txn.date,
                    "type": "PAYMENT",
                    "reference": txn.reference or f"PAY-{txn.id}",
                    "debit": None,
                    "credit": txn.amount,
                    "sort_key": (txn.date, 2, txn.id),
                }
                for txn in payments
            ]
        )

    @classmethod
    def opening_balance(cls, *, transporter_id=None, date_from=None, date_to=None):
        return opening_balance(entries_of(cls, transporter_id, cls._parties()), date_from=date_from, direction=cls.DIRECTION)

    @classmethod
    def run(cls, *, transporter_id=None, date_from=None, date_to=None) -> list[dict]:
        return statement_rows(
            entries_of(cls, transporter_id, cls._parties()), date_from=date_from, date_to=date_to, direction=cls.DIRECTION
        )
