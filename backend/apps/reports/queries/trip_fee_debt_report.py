# TripFeeDebtReportQuery - "dettes de frais de trajet" (docs/superpowers/specs/
# 2026-09-23-rapports-capital-dettes-creances-design.md, section 3). Situation
# courante: the period params are accepted and ignored.

from decimal import Decimal

from apps.reports.queries.debt_common import FEE_TYPES, fee_debt_rows

ZERO = Decimal("0.00")

# Business columns only; the technical row["section"] key is not exported.
FIELDS = [
    "fee_type",
    "date",
    "trips",
    "notes",
    "count",
    "total_amount",
    "paid_amount",
    "remaining_amount",
    "status",
]


class TripFeeDebtReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, fee_type="all", date_from=None, date_to=None) -> list[dict]:
        fee_type = fee_type or "all"
        if fee_type != "all" and fee_type not in FEE_TYPES:
            raise ValueError(f"Type de frais inconnu : '{fee_type}'.")
        types = FEE_TYPES if fee_type == "all" else [fee_type]

        rows = [{"section": "line", **row} for row in fee_debt_rows(types)]
        for debt_type in types:
            own = [row for row in rows if row["fee_type"] == debt_type]
            if own:
                rows.append(
                    {
                        "section": "type_total",
                        "fee_type": debt_type,
                        "count": len(own),
                        "total_amount": sum((r["total_amount"] for r in own), ZERO),
                        "paid_amount": sum((r["paid_amount"] for r in own), ZERO),
                        "remaining_amount": sum((r["remaining_amount"] for r in own), ZERO),
                    }
                )
        return rows
