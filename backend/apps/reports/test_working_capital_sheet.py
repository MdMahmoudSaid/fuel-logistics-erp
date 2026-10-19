# The Fond de roulement PDF follows the client's "Etat de la tresorerie" sheet:
# title band, numbered rows, a TOTAL row per section, the final figure.
import io
from decimal import Decimal as D

from pypdf import PdfReader

from apps.reports.services.working_capital_pdf import (
    WORKING_CAPITAL_LINES,
    render_working_capital_pdf,
)

WC = {
    "total": D("481224102"), "capital": D("388865602"), "shareholder_dues": D("388865602"),
    "treasury_available": D("421338383"), "customer_receivables": D("231813219"),
    "supplier_debt_total": D("171927500"), "transporter_debt_total": D("0"), "other_debts": D("0"),
    "supplier_reliquat_value": D("0"), "supplier_in_transit_value": D("0"),
    "supplier_company_stock_value": D("0"), "advances_paid": D("0"), "unsold_costs": D("0"),
}


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_sheet_layout_lists_accounts_customers_totals_and_the_final_figure():
    text = _text(render_working_capital_pdf(
        working_capital=WC, lines=list(WORKING_CAPITAL_LINES), lang="fr",
        treasury_accounts=[("BDM", D("140000000")), ("Caisse 1", D("281338383"))],
        customer_receivables=[("Client A", D("231813219"))],
    ))
    assert "ETAT DU FOND DE ROULEMENT" in text
    for expected in ("TRESORERIE", "BDM", "Caisse 1", "ETAT DES CREANCES", "Client A",
                     "DETTES (A DEDUIRE)", "-171 927 500", "FOND DE ROULEMENT", "481 224 102"):
        assert expected in text, expected
    assert text.count("TOTAL") >= 2  # treasury and debts sections each close with a total


def test_only_the_selected_lines_are_printed():
    text = _text(render_working_capital_pdf(working_capital=WC, lines=["treasury"], lang="en"))
    assert "TREASURY" in text and "Available treasury" in text
    assert "DEBTS" not in text
