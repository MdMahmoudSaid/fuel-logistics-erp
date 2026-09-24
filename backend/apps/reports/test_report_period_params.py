# "Situation courante" reports accept and ignore period params (spec 2026-09-23-
# rapports-capital-dettes-creances, section Périodes): a direct request with
# dates answers 200 with exactly the payload it gives without dates.

import pytest
from rest_framework.test import APIClient

from apps.reports.test_queries import _make_admin, _make_full_trip

PERIODLESS_SLUGS = [
    "customer-outstanding",
    "supplier-outstanding",
    "transporter-outstanding",
    "fuel-stock",
]
PERIOD_QUERIES = [
    {"from": "2026-01-01", "to": "2026-09-23"},
    {"range": "this_month"},
    {"preset": "last_7_days"},
]


def _client(suffix):
    admin_user = _make_admin(suffix)
    _make_full_trip(suffix, admin_user)
    client = APIClient()
    client.force_authenticate(admin_user)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("slug", PERIODLESS_SLUGS)
@pytest.mark.parametrize("period", PERIOD_QUERIES)
def test_periodless_report_ignores_period_params(slug, period):
    client = _client("PERIODLESS")

    plain = client.get(f"/api/reports/{slug}/")
    dated = client.get(f"/api/reports/{slug}/", period)

    assert plain.status_code == 200 and dated.status_code == 200
    assert dated.json() == plain.json()


@pytest.mark.django_db
@pytest.mark.parametrize("slug", PERIODLESS_SLUGS)
def test_periodless_document_is_as_of_even_when_dates_are_sent(slug):
    client = _client("PERIODDOC")

    document = client.get(
        f"/api/reports/{slug}/", {"from": "2026-01-01", "to": "2026-09-23", "document": "1"}
    ).json()["document"]

    assert document["period"]["mode"] == "as_of"
    assert document["period"]["from"] is None and document["period"]["to"] is None
