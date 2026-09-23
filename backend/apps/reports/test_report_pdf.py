# Report PDF renderer tests (docs/superpowers/specs/2026-09-23-rapports-
# document-comptable-design.md, sections report_pdf and Testing item 7).
# Text is read back with pypdf; NBSP grouping is normalised to plain spaces.

import io
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader
from rest_framework.test import APIClient

from apps.reports.services.report_document import build_report_document
from apps.reports.services.report_pdf import build_report_flowables, render_report_pdf
from apps.reports.test_queries import _make_admin, _make_full_trip

D = Decimal
TODAY = date(2026, 9, 23)


def pdf_pages(content):
    reader = PdfReader(io.BytesIO(content))
    return reader, [page.extract_text().replace("\xa0", " ") for page in reader.pages]


def render(slug, rows, params=None, lang="fr", context=None):
    document = build_report_document(slug, rows, params or {}, lang, statement_context=context, generated_on=TODAY)
    return document, render_report_pdf(document, rows, lang)


STATEMENT_ROWS = [
    {"date": date(2026, 9, 2), "type": "INVOICE", "reference": "FAC-1", "debit": D("1250000.00"),
     "credit": None, "balance": D("1750000.00")},
    {"date": date(2026, 9, 3), "type": "PAYMENT", "reference": "PAY-1", "debit": None,
     "credit": D("300000.00"), "balance": D("1450000.00")},
]


def purchase_rows(count):
    return [
        {"reference": f"SO-{i:04d}", "purchase_date": date(2026, 9, 1), "supplier": f"Fournisseur {i}",
         "product": "Gasoil", "quantity_litres": D("45000.00"), "unit_price": D("600.0000"),
         "total_amount": D("27000000.00"), "status": "CONFIRMED"}
        for i in range(count)
    ]


def test_french_statement_pdf_has_masthead_info_table_opening_row_and_summary():
    _, content = render("customer-statement", STATEMENT_ROWS,
                        {"date_from": "2026-09-01", "date_to": "2026-09-23"},
                        context={"opening_balance": D("500000.00")})
    reader, pages = pdf_pages(content)
    text = "\n".join(pages)

    assert content.startswith(b"%PDF-") and len(reader.pages) == 1
    for expected in ("AZUR ÉNERGIE", "Relevé client", "Généré le", "23/09/2026", "Du 01/09/2026 au 23/09/2026",
                     "XOF", "Date", "Type", "Référence", "Débit", "Crédit", "Solde", "Facture", "Paiement",
                     "02/09/2026", "FAC-1", "1 250 000 XOF", "Solde antérieur", "500 000 XOF",
                     "Total débit", "Total crédit", "Mouvement net de la période", "Solde final",
                     "1 450 000 XOF", "Page 1 / 1"):
        assert expected in text, expected
    assert "trip_reference" not in text and "MONEY_IN" not in text


@pytest.mark.django_db
def test_pdf_shows_the_selected_entity_and_survives_hostile_names():
    from apps.customers.models import Customer

    customer = Customer.objects.create(name="Ets <img src=x> & Frères <b>" + "X" * 120)
    document, content = render("customer-statement", STATEMENT_ROWS, {"customer_id": customer.id},
                               context={"opening_balance": D("0")})
    text = " ".join(pdf_pages(content)[1]).replace("\n", "")

    assert document["entity"]["label"] == "Client"
    assert "Ets <img src=x> & Frères <b>" in text.replace(" ", " ")
    hostile_rows = [{**STATEMENT_ROWS[0], "reference": "<script>&amp;</script>"}]
    _, content = render("customer-statement", hostile_rows, context={"opening_balance": D("0")})
    assert "<script>&amp;</script>" in " ".join(pdf_pages(content)[1])


def test_empty_report_keeps_header_columns_empty_line_and_summary():
    _, content = render("purchase-report", [])
    _, pages = pdf_pages(content)
    text = "\n".join(pages)

    assert "Rapport des achats" in text and "Référence" in text and "Fournisseur" in text
    assert "Aucune donnée pour la période sélectionnée." in text
    assert "Montant total" in text and "Annulés exclus" in text and "Page 1 / 1" in text


def test_long_report_paginates_repeating_title_and_column_headers_with_correct_total():
    document, content = render("purchase-report", purchase_rows(150))
    reader, pages = pdf_pages(content)

    assert len(pages) >= 2
    box = reader.pages[0].mediabox
    assert box.width > box.height  # landscape for a wide report
    for number, text in enumerate(pages, start=1):
        assert f"Page {number} / {len(pages)}" in text
        assert "Référence" in text and "Fournisseur" in text  # table header repeated
        if number > 1:
            assert "Rapport des achats" in text and "AZUR ÉNERGIE" in text  # running title
    assert "Montant total" in pages[-1]


def test_portrait_report_is_portrait():
    reader, _ = pdf_pages(render("expense-report", [])[1])
    box = reader.pages[0].mediabox

    assert box.height > box.width


@pytest.mark.django_db
def test_margin_report_prints_three_tables_that_fit_the_page_with_readable_fonts():
    from apps.reports.queries.margin_report import FIELDS

    row = {field: D("1234567.00") for field in FIELDS}
    row.update({"trip_reference": "TRIP-MARGIN-1", "client": "Client", "product": "Gasoil"})
    document = build_report_document("margin-report", [row] * 3, {}, "fr", generated_on=TODAY)
    flowables, available = build_report_flowables(document, [row] * 3, "fr")
    tables = [f for f in flowables if f.__class__.__name__ == "Table" and f.repeatRows]

    assert len(tables) == 3
    for table in tables:
        assert sum(table._colWidths) <= available + 0.01
        for row_cells in table._cellvalues:
            for cell in row_cells:
                if hasattr(cell, "style"):
                    assert cell.style.fontSize >= 7
    text = "\n".join(pdf_pages(render_report_pdf(document, [row] * 3, "fr"))[1])
    assert "Quantités et prix" in text and "Coûts" in text and "Pertes et marge" in text
    assert "1 234 567 XOF" in text and "Coût réel total" in text


def test_treasury_pdf_prints_the_signed_reconciliation_equation():
    rows = [{"date": date(2026, 9, 5), "type": "MONEY_IN", "amount": D("500.00"), "reference": "R1", "balance": D("1400.00")}]
    context = {"opening_balance": D("900.00"), "transfers_net": D("-30.00"), "closing_balance": D("1370.00")}
    _, pages = pdf_pages(render("bank-statement", rows, context=context)[1])
    text = "\n".join(pages)

    for expected in ("Solde antérieur", "Total entrées", "Total sorties", "Virements internes (net)",
                     "-30 XOF", "Solde final", "1 370 XOF", "Entrée"):
        assert expected in text, expected
    assert "Écart de rapprochement" not in text


def test_none_cells_print_a_dash():
    rows = [{"trip_reference": "T1", "loading_date": date(2026, 9, 1), "status": "DELIVERED",
             "quantity_loaded": D("100"), "client": None, "current_margin": None}]
    _, pages = pdf_pages(render("truck-history", rows)[1])

    assert "—" in "\n".join(pages)


@pytest.mark.django_db
@pytest.mark.parametrize("params", [{}, {"lang": "fr"}])
def test_export_pdf_endpoint_returns_the_new_document(params):
    admin_user = _make_admin("PDFEXPORT")
    _make_full_trip("PDFEXPORT", admin_user)
    client = APIClient()
    client.force_authenticate(admin_user)

    response = client.get("/api/reports/trip-report/", {"export": "pdf", **params})

    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert 'filename="trip-report.pdf"' in response["Content-Disposition"]
    text = "\n".join(pdf_pages(response.content)[1])
    assert "Rapport des trajets" in text and "AZUR ÉNERGIE" in text and "Nombre de trajets" in text
    assert "TRIP-QUERY-PDFEXPORT" in text.replace("\n", "")
