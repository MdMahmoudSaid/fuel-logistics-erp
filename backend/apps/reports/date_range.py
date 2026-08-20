# Shared date-range resolution for report/dashboard endpoints
# (docs/PHASE_6_PLAN.md Etape 5: "?range=...&from=...&to=..."; guide
# Section 9.6: "Support date filters centrally").

from datetime import timedelta

from django.utils import timezone


def resolve_date_range(query_params):
    """Explicit from/to wins outright; otherwise a named `range` resolves
    to a (from, to) pair anchored on today; with neither, both are None
    (no filtering - the full-history view)."""
    date_from = query_params.get("from")
    date_to = query_params.get("to")
    if date_from or date_to:
        return date_from, date_to

    today = timezone.localdate()
    range_key = query_params.get("range")
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
