# Recursively renders Decimal as its exact string form before a plain dict
# goes into a DRF Response() (docs/PHASE_6_PLAN.md Etape 5).
#
# DRF's default JSON encoder coerces a bare Decimal to float when it isn't
# routed through a serializer DecimalField - fine for most APIs, but these
# dashboard/report views hand back financial totals directly as dicts, and
# a silent Decimal->float trip would let binary floating-point rounding
# noise leak into money figures.

from decimal import Decimal


def decimals_to_str(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: decimals_to_str(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [decimals_to_str(item) for item in value]
    return value
