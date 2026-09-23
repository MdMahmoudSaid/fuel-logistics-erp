# GeneralDebtReportQuery - "dettes generales" (docs/superpowers/specs/2026-09-23-
# rapports-capital-dettes-creances-design.md, section 4): suppliers, transporters
# and trip fees, built from the same get_payable_debts() calls as the payment
# screen. Situation courante: the period params are accepted and ignored.

from apps.reports.queries.debt_common import FEE_TYPES, fee_debt_rows, supplier_debt_rows, transporter_debt_rows

# Business columns only; the technical row["section"] key is not exported.
FIELDS = [
    "supplier",
    "transporter",
    "reference",
    "trip_reference",
    "fee_type",
    "date",
    "trips",
    "notes",
    "total_amount",
    "paid_amount",
    "remaining_amount",
    "status",
]


class GeneralDebtReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        return (
            [{"section": "supplier", **row} for row in supplier_debt_rows()]
            + [{"section": "transporter", **row} for row in transporter_debt_rows()]
            + [{"section": "trip_fee", **row} for row in fee_debt_rows(FEE_TYPES)]
        )
