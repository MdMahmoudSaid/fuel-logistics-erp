"""Benefices PDF in "Periode en cours": adjustment rows are labelled and
revenue comes from the rows' own revenue (spec 2026-10-05, 3.6)."""

import io
from decimal import Decimal

import pytest
from pypdf import PdfReader
from rest_framework.test import APIClient

from apps.finance.test_current_period_figures import _close, _sell, _trip, _trip_fee
from apps.trips.tests import _setup_fixtures


@pytest.mark.django_db
def test_profit_pdf_marks_adjustment_rows_of_the_open_period():
    fx = _setup_fixtures("CUR-PDF")
    trip = _trip(fx, "TRIP-CUR-PDF")
    _sell(fx, trip)
    _close(fx)
    _trip_fee(trip, Decimal("90000.00"))
    client = APIClient()
    client.force_authenticate(fx["admin_user"])

    response = client.get("/api/shareholders/profit-preview/pdf/", {"preset": "period", "lang": "fr"})

    assert response.status_code == 200
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
    assert "ajustement" in text.lower()
