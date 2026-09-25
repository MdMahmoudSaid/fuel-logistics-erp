from decimal import Decimal
from unittest import mock

from apps.reports.queries.margin_report import MarginReportQuery


def seed_net_profit(amount=Decimal("10000000.00")):
    """Give every period a real, computed net profit of `amount` (no
    general expense) so ShareholderDistributionService.validate_distribution's
    amount guard - which since 2026-09-25 compares against the period's net
    profit, not the treasury - clears in tests where the guard itself is not
    under test. Stopped automatically after each test (backend/conftest.py).
    """
    row = {
        "current_margin": Decimal(str(amount)),
        "company_absorbed_loss_amount": Decimal("0.00"),
    }
    mock.patch.object(MarginReportQuery, "run", return_value=[row]).start()
