"""The brand (name + logo) this installation runs under.

One codebase serves several customers that differ only by name and logo: the
`BRAND` environment variable picks the entry below (default `azur`). Add a
customer = add an entry here + its logo in apps/reports/assets/, and the
matching folder in frontend/brands/.
"""

import os
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "reports" / "assets"

BRANDS = {
    "azur": {"name": "AZUR ÉNERGIE", "logo": _ASSETS / "azur-energie-icon.png"},
    "sahel": {"name": "SAHEL COMMERCE", "logo": _ASSETS / "sahel-commerce-icon.png"},
}

BRAND_KEY = os.environ.get("BRAND", "azur").strip().lower()
if BRAND_KEY not in BRANDS:
    raise RuntimeError(f"Unknown BRAND {BRAND_KEY!r}: expected one of {sorted(BRANDS)}")

BRAND_NAME = BRANDS[BRAND_KEY]["name"]
BRAND_LOGO_PATH = BRANDS[BRAND_KEY]["logo"]
