# Shared date-range resolution for report/dashboard endpoints
# (docs/PHASE_6_PLAN.md Etape 5: date filters; guide Section 9.6:
# "Support date filters centrally").

from datetime import timedelta

from django.apps import apps
from django.db import connection
from django.utils import timezone

_profit_period_table_ready = None


def _current_open_profit_period_start():
    """Start date of the open ShareholderProfitPeriod, or None if the
    feature's table doesn't exist yet or no period is currently open.

    Lazy table-existence check keeps this module safe to import and call
    even where the ShareholderProfitPeriod migration hasn't run.
    """
    global _profit_period_table_ready
    if _profit_period_table_ready is None:
        _profit_period_table_ready = (
            "finance_shareholderprofitperiod" in connection.introspection.table_names()
        )
    if not _profit_period_table_ready:
        return None
    Period = apps.get_model("finance", "ShareholderProfitPeriod")
    open_period = Period.objects.filter(status="OPEN").only("start_date").first()
    return open_period.start_date if open_period else None


def resolve_date_range(query_params):
    """Explicit dates win outright; otherwise a named preset resolves to a
    (from, to) pair anchored on today; with neither, both are None
    (no filtering - the full-history view).

    Accept both the current frontend contract (preset/start_date/end_date)
    and the older report aliases (range/from/to), plus start/end for API
    callers that use shorter names.
    """
    date_from = (
        query_params.get("start_date")
        or query_params.get("from")
        or query_params.get("start")
    )
    date_to = (
        query_params.get("end_date")
        or query_params.get("to")
        or query_params.get("end")
    )
    if date_from or date_to:
        return date_from, date_to

    today = timezone.localdate()
    range_key = query_params.get("preset") or query_params.get("range")
    if range_key == "period":
        # Client decision (2026-10-04): "la periode en cours" means the
        # open ShareholderProfitPeriod window, not a calendar preset - the
        # revenue/collections/operating-profit cards that say "de la
        # periode" must reset to zero the moment a new period opens, same
        # as the distribution-aware net profit figure already does. No
        # period open (or the feature unused here) falls back to the
        # full-history view rather than hiding data behind a filter
        # nothing has configured yet.
        start = _current_open_profit_period_start()
        return (start, today) if start else (None, None)
    if range_key == "today":
        return today, today
    if range_key == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if range_key == "week":
        return today - timedelta(days=today.weekday()), today
    if range_key == "month":
        return today.replace(day=1), today
    if range_key == "year":
        return today.replace(month=1, day=1), today
    return None, None


def is_current_period(query_params) -> bool:
    """True for the "Periode en cours" preset with no explicit dates: its
    figures are measured from the last closure (apps.finance.
    profit_periods), not from a date window."""
    explicit = any(
        query_params.get(key)
        for key in ("start_date", "from", "start", "end_date", "to", "end")
    )
    preset = query_params.get("preset") or query_params.get("range")
    return preset == "period" and not explicit
