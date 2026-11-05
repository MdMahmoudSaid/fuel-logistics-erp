import re

from django.utils import timezone


def generate_monthly_reference(
    model, field_name, prefix, width=4, now=None, allow_suffix=False
) -> str:
    """Next PREFIX-YYYYMM-NNNN for `model.field_name`, scoped to the current
    calendar month.

    Reads the current highest matching value and increments it - there's no
    dedicated sequence table (same trade-off as
    apps.trips.views._generate_next_reference). Callers are responsible for
    retrying on IntegrityError to cover the race between two concurrent
    creates picking the same number.

    The regex restricts the lookup to values matching our own generated
    format (exact prefix, exact month, fixed-width digits) - hand-typed or
    legacy references in a different format are ignored rather than
    corrupting the count or being mistaken for the highest value.
    """
    now = now or timezone.now()
    yyyymm = now.strftime("%Y%m")
    full_prefix = f"{prefix}-{yyyymm}-"
    # allow_suffix: references like PREFIX-YYYYMM-NNNN-<free text> (invoices
    # carry their truck number after the sequence) still count in the sequence.
    tail = r"(-.+)?" if allow_suffix else ""
    pattern = rf"^{re.escape(full_prefix)}\d{{{width}}}{tail}$"

    last = (
        model.objects.filter(**{f"{field_name}__regex": pattern})
        .order_by(f"-{field_name}")
        .first()
    )
    last_number = 0
    if last:
        try:
            last_number = int(getattr(last, field_name)[len(full_prefix) : len(full_prefix) + width])
        except ValueError:
            last_number = 0

    return f"{full_prefix}{last_number + 1:0{width}d}"
