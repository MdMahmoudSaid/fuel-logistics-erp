import datetime
from decimal import Decimal

import pytest

from apps.reports.services.profit_pdf import PROFIT_PDF_LABELS, render_profit_report_pdf

ZERO = Decimal("0.00")


def _preview(**overrides) -> dict:
    base = {
        "period_start": datetime.date(2026, 9, 1),
        "period_end": datetime.date(2026, 9, 6),
        "current_profit": Decimal("4874000.00"),
        "operational_profit": Decimal("4874000.00"),
        "general_expenses_paid": Decimal("0.00"),
        "revenue": Decimal("0.00"),
        "net_profit": Decimal("4874000.00"),
        "total_company_absorbed_loss": Decimal("0.00"),
        "working_capital": {
            "capital": Decimal("0.00"),
            "treasury_available": Decimal("300000000.00"),
            "customer_receivables": Decimal("86000000.00"),
            "supplier_debt_total": Decimal("45000000.00"),
            "transporter_debt_total": Decimal("2925000.00"),
            "other_debts": Decimal("10255000.00"),
            "supplier_reliquat_value": Decimal("15000000.00"),
            "supplier_in_transit_value": Decimal("5000000.00"),
            "supplier_company_stock_value": Decimal("3000000.00"),
            "gross": Decimal("386000000.00"),
            "total": Decimal("467180000.00"),
        },
        "already_distributed": Decimal("0.00"),
        "already_validated_in_period": Decimal("0.00"),
        "result_after_debts_and_capital": Decimal("385937000.00"),
        "distributable_result": Decimal("385937000.00"),
        "shareholders": [],
    }
    base.update(overrides)
    return base


def _other_debts_breakdown(**overrides) -> dict:
    base = {
        "customs": Decimal("5000000.00"),
        "transit": Decimal("2000000.00"),
        "road_transit": Decimal("1255000.00"),
        "other": Decimal("2000000.00"),
    }
    base.update(overrides)
    return base


def _margin_row(**overrides) -> dict:
    base = {
        "trip_reference": "TRIP-000002",
        "client": "Client Test Mohamed",
        "product": "Gasoil",
        "quantity": Decimal("45000.00"),
        "quantity_loaded": Decimal("45000.00"),
        "quantity_invoiced": Decimal("45000.00"),
        "transporter_loss_quantity": Decimal("130.00"),
        "transporter_loss_indemnity": Decimal("117000.00"),
        "company_absorbed_loss_quantity": Decimal("0.00"),
        "company_absorbed_loss_amount": Decimal("0.00"),
        "supplier_unit_price": Decimal("500.0000"),
        "transport_cost": Decimal("500000.00"),
        "customs_cost": Decimal("0.00"),
        "transit_cost": Decimal("0.00"),
        "road_transit_cost": Decimal("0.00"),
        "border_cost": Decimal("0.00"),
        "loading_cost": Decimal("0.00"),
        "additional_costs": Decimal("0.00"),
        "real_total_cost": Decimal("35680000.00"),
        "unit_cost": Decimal("792.89"),
        "unit_selling_price": Decimal("900.0000"),
        "unit_profit": Decimal("107.11"),
        "current_margin": Decimal("4874000.00"),
    }
    base.update(overrides)
    return base


def test_render_profit_report_pdf_produces_valid_pdf_bytes():
    pdf_bytes = render_profit_report_pdf(
        preview=_preview(),
        other_debts_breakdown=_other_debts_breakdown(),
        rows=[_margin_row()],
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.parametrize("lang", ["fr", "en", "ar"])
def test_render_profit_report_pdf_all_langs_do_not_crash(lang):
    pdf_bytes = render_profit_report_pdf(
        preview=_preview(),
        other_debts_breakdown=_other_debts_breakdown(),
        rows=[_margin_row()],
        lang=lang,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_render_profit_report_pdf_handles_empty_trip_list():
    # No trips in the period at all - the detail-table section must be
    # skipped entirely (never an empty table with just a header), and
    # nothing else in the document should crash on an empty rows list.
    pdf_bytes = render_profit_report_pdf(
        preview=_preview(
            operational_profit=ZERO, net_profit=ZERO, current_profit=ZERO,
        ),
        other_debts_breakdown={"customs": ZERO, "transit": ZERO, "road_transit": ZERO, "other": ZERO},
        rows=[],
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_render_profit_report_pdf_handles_no_period_selected():
    # period_start/period_end both None (get_preview()'s own "since the
    # last validated distribution" default, when that's also None -
    # meaning no distribution has ever been validated) - must fall back to
    # an "all time" label rather than crash formatting `None`.
    pdf_bytes = render_profit_report_pdf(
        preview=_preview(period_start=None, period_end=None),
        other_debts_breakdown=_other_debts_breakdown(),
        rows=[_margin_row()],
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_render_profit_report_pdf_handles_negative_distributable_result():
    # Losses/large debts can push distributable_result negative - the
    # money formatter must handle a negative Decimal without crashing.
    pdf_bytes = render_profit_report_pdf(
        preview=_preview(result_after_debts_and_capital=Decimal("-1500000.00")),
        other_debts_breakdown=_other_debts_breakdown(),
        rows=[_margin_row(current_margin=Decimal("-200000.00"), unit_profit=Decimal("-4.44"))],
        lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_render_profit_report_pdf_many_trips_do_not_crash():
    rows = [_margin_row(trip_reference=f"TRIP-{i:06d}") for i in range(50)]
    pdf_bytes = render_profit_report_pdf(
        preview=_preview(), other_debts_breakdown=_other_debts_breakdown(), rows=rows, lang="fr",
    )
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_profit_pdf_pipeline_labels_describe_payment_allocation_not_extra_debts(lang):
    """Client recette 2026-09-24: "Stock fournisseur (reliquat non charge)"
    was read as a second supplier debt. The three lines are now labelled as
    what they are - where supplier payments are allocated."""
    labels = PROFIT_PDF_LABELS[lang]
    expected = {
        "fr": {
            "supplierReliquat": "Paye : chez le fournisseur",
            "supplierInTransit": "Paye : en cours",
            "supplierCompanyStock": "Paye : stock entreprise",
        },
        "en": {
            "supplierReliquat": "Paid: at the supplier",
            "supplierInTransit": "Paid: in transit",
            "supplierCompanyStock": "Paid: company stock",
        },
    }[lang]
    for key, text in expected.items():
        assert labels[key] == text
    assert all("Stock fournisseur" not in v and "Supplier stock" not in v for v in labels.values() if isinstance(v, str))


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_profit_pdf_lists_pipeline_lines_in_allocation_order(lang):
    """Client request 2026-09-24: company stock, then en cours, then the
    reliquat - the same order supplier payments are allocated in."""
    import io

    from pypdf import PdfReader

    pdf_bytes = render_profit_report_pdf(
        preview=_preview(),
        other_debts_breakdown=_other_debts_breakdown(),
        rows=[_margin_row()],
        lang=lang,
    )
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    labels = PROFIT_PDF_LABELS[lang]
    positions = [
        text.index(labels[key])
        for key in ("supplierCompanyStock", "supplierInTransit", "supplierReliquat")
    ]
    assert positions == sorted(positions)
