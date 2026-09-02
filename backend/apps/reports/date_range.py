# Shared date-range resolution for report/dashboard endpoints
# (docs/PHASE_6_PLAN.md Etape 5: date filters; guide Section 9.6:
# "Support date filters centrally").

from datetime import timedelta

from django.utils import timezone


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
