# CapitalReportQuery - "rapport de capital" (docs/superpowers/specs/2026-09-23-
# rapports-capital-dettes-creances-design.md, section 1).
#
# Section "shareholder": current capital of EVERY shareholder (never filtered
# by period, active or not, so the sum equals get_total_capital()). Section
# "contribution": the contributions recorded inside the period.

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.finance.models import Shareholder, ShareholderContribution
from apps.finance.services import ShareholderContributionService

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# Business columns only; the technical row["section"] key is not exported.
FIELDS = [
    "shareholder",
    "participation_percent",
    "opening_contribution",
    "later_contributions",
    "gross_capital",
    "capital_percent",
    "date",
    "amount",
    "account",
    "reference",
    "notes",
]


class CapitalReportQuery:
    FIELDS = FIELDS

    @classmethod
    def run(cls, *, date_from=None, date_to=None) -> list[dict]:
        total_capital = ShareholderContributionService.get_total_capital()
        later = dict(
            ShareholderContribution.objects.filter(cancelled_at__isnull=True)
            .values("shareholder_id")
            .annotate(total=Sum("amount"))
            .values_list("shareholder_id", "total")
        )
        rows = []
        for shareholder in Shareholder.objects.order_by("name", "id"):
            opening = shareholder.contribution
            extra = later.get(shareholder.id) or ZERO
            gross = opening + extra
            share = (gross * 100 / total_capital).quantize(CENT, ROUND_HALF_UP) if total_capital else ZERO
            rows.append(
                {
                    "section": "shareholder",
                    "shareholder": shareholder.name,
                    "participation_percent": shareholder.participation_percent,
                    "opening_contribution": opening,
                    "later_contributions": extra,
                    "gross_capital": gross,
                    "capital_percent": share,
                }
            )

        contributions = (
            ShareholderContribution.objects.filter(cancelled_at__isnull=True)
            .select_related("shareholder", "bank_account", "cash_account")
            .order_by("date", "id")
        )
        if date_from:
            contributions = contributions.filter(date__gte=date_from)
        if date_to:
            contributions = contributions.filter(date__lte=date_to)
        for contribution in contributions:
            account = contribution.bank_account or contribution.cash_account
            rows.append(
                {
                    "section": "contribution",
                    "date": contribution.date,
                    "shareholder": contribution.shareholder.name,
                    "amount": contribution.amount,
                    "account": account.name if account else None,
                    "reference": contribution.reference,
                    "notes": contribution.notes,
                }
            )
        return rows
