# The company footer (Informations de l'entreprise page) is stamped on every
# page of every PDF the app renders, not only the commercial documents.

import io

import pytest
from pypdf import PdfReader

from apps.core.models import CompanyProfile
from apps.reports.services.working_capital_pdf import render_working_capital_pdf

_KEYS = [
    "total", "gross", "capital", "treasury_available", "customer_receivables", "supplier_debt_total",
    "transporter_debt_total", "other_debts", "shareholder_dues", "supplier_reliquat_value",
    "supplier_in_transit_value", "supplier_company_stock_value",
]


@pytest.mark.django_db
def test_company_footer_is_printed_on_a_report_pdf_that_is_not_a_commercial_document():
    CompanyProfile.objects.update_or_create(
        pk=1,
        defaults={
            "name": "AZUR ENERGIE. SARL", "address": "BAMAKO MALI", "city": "BAMAKO",
            "phone": "76202611", "email": "azur@example.com", "tax_id": "085161087V", "trade_register": "ML",
        },
    )
    pdf = render_working_capital_pdf(working_capital={k: 0 for k in _KEYS}, lines=["total"], lang="fr")

    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()

    assert "AZUR ENERGIE" in text
    assert "SARL" not in text  # the legal form is never printed next to the name
    assert "NIF : 085161087V" in text
    assert "Page 1 / 1" in text
