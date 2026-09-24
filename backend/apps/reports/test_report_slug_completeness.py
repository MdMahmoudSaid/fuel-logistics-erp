# The same 22 report slugs must exist in the API registry, the document specs,
# the label catalog and the frontend selector (REPORT_TYPES), so a report can
# never work in the API but be missing from the sheet or the selector.
# Also pins the export/legacy contract of the reports added on 2026-09-23.

import re
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from apps.reports.services.report_document import REPORT_SPECS
from apps.reports.services.report_labels import LABELS
from apps.reports.test_queries import _make_admin
from apps.reports.views.reports import REPORT_REGISTRY

TYPES_TS = Path(__file__).resolve().parents[3] / "frontend/src/modules/reports/types.ts"
NEW_SLUGS = [
    "capital-report",
    "general-expense-report",
    "trip-fee-debt-report",
    "general-debt-report",
    "general-receivable-report",
]
# Reports that need no entity id: callable as-is against an empty database.
NO_PARAM_SLUGS = [
    slug for slug in REPORT_REGISTRY
    if not slug.endswith("-statement") and slug != "truck-history"
]


def frontend_slugs():
    source = TYPES_TS.read_text(encoding="utf-8")
    body = source.split("export const REPORT_TYPES", 1)[1].split("\n]\n", 1)[0]
    return re.findall(r"value: '([a-z-]+)'", body)


def test_the_same_22_slugs_exist_in_registry_specs_labels_and_frontend_selector():
    slugs = set(REPORT_REGISTRY)

    assert len(slugs) == 22 and set(NEW_SLUGS) <= slugs
    assert set(REPORT_SPECS) == slugs
    assert set(frontend_slugs()) == slugs and len(frontend_slugs()) == 22  # no duplicate entry
    for lang in LABELS:
        assert all(LABELS[lang].get(f"title.{slug}") for slug in slugs)


@pytest.fixture
def client():
    client = APIClient()
    client.force_authenticate(_make_admin("SLUGCOMP"))
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("slug", NO_PARAM_SLUGS)
def test_legacy_payload_keeps_its_three_keys_and_business_fields_only(client, slug):
    payload = client.get(f"/api/reports/{slug}/").json()

    assert set(payload) == {"report_type", "fields", "rows"}
    assert payload["fields"] == list(REPORT_REGISTRY[slug].FIELDS) and "section" not in payload["fields"]


@pytest.mark.django_db
@pytest.mark.parametrize("slug", NEW_SLUGS)
@pytest.mark.parametrize("fmt,content_type", [("csv", "text/csv"), ("xlsx", "spreadsheetml"), ("pdf", "application/pdf")])
def test_new_reports_export_in_every_format_even_when_empty(client, slug, fmt, content_type):
    response = client.get(f"/api/reports/{slug}/", {"export": fmt})

    assert response.status_code == 200 and content_type in response["Content-Type"]


@pytest.mark.django_db
def test_csv_export_of_a_sectioned_report_has_no_technical_column_and_keeps_rows(client):
    from datetime import date
    from decimal import Decimal

    from apps.finance.models import Expense

    Expense.objects.create(
        category="rent", amount=Decimal("100000.00"), calculation_method="MANUAL", date=date(2026, 9, 1)
    )

    text = client.get("/api/reports/general-expense-report/", {"export": "csv"}).content.decode("utf-8-sig")
    header, *lines = text.strip().splitlines()

    assert "section" not in header and header.startswith("date,category")
    assert len(lines) == 2  # the expense line and its category recap line
