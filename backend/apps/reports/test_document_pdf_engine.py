from apps.reports.services.report_pdf import build_report_flowables, render_report_pdf


def _doc(lang, **extra):
    document = {
        "company": {"name": "AZUR ÉNERGIE"}, "title": "T", "lang": lang,
        "direction": "rtl" if lang == "ar" else "ltr", "orientation": "portrait", "info": [],
        "tables": [{"title": "", "columns": [{"field": "a", "label": "A", "kind": "text", "align": "start"}]}],
        "opening_balance": None, "summary": [], "labels": {"page": "Page"}, "empty_text": "-",
    }
    document.update(extra)
    return document


def test_engine_without_new_keys_still_renders():
    assert render_report_pdf(_doc("fr"), [{"a": "x"}]).startswith(b"%PDF")


def test_engine_with_blocks_signatures_and_company_lines_in_arabic():
    document = _doc(
        "ar",
        company={"name": "Sahel", "tagline": "Un partenaire", "lines": ["NIF : 1"]},
        blocks=[{"title": "المبلغ", "text": "ألف فرنك", "boxed": True}],
        signatures=["المستلم", "المورد"],
    )
    flowables, _ = build_report_flowables(document, [{"a": "BP 8795 MD"}])
    # header + table + blocks + signatures + footer all present
    assert len(flowables) >= len(build_report_flowables(_doc("ar"), [{"a": "x"}])[0]) + 3
    assert render_report_pdf(document, [{"a": "BP 8795 MD"}]).startswith(b"%PDF")


def test_number_kind_has_no_unit_and_trims_decimals():
    """Priced documents print quantities in any unit (M3, L...) and 4-decimal
    unit prices: the 'number' kind adds no ' L' / 'XOF/L' suffix."""
    from decimal import Decimal

    from apps.reports.services.report_pdf import NBSP, _cell_text

    column = {"kind": "number"}
    assert _cell_text(column, Decimal("500.00")) == "500"
    assert _cell_text(column, Decimal("775000.0000")) == f"775{NBSP}000"
    assert _cell_text(column, Decimal("1234.5600")) == f"1{NBSP}234,56"


def test_money_kind_uses_the_document_currency():
    from decimal import Decimal

    from apps.reports.services.report_pdf import NBSP, _cell_text, _summary_text

    assert _cell_text({"kind": "money", "currency": "EUR"}, Decimal("12000.5")) == f"12{NBSP}000,50{NBSP}EUR"
    assert _summary_text({"kind": "money", "currency": "EUR", "value": Decimal("1")}) == f"1,00{NBSP}EUR"
    assert _cell_text({"kind": "money"}, Decimal("12000")).endswith("XOF")


def test_very_long_notes_do_not_break_the_pdf():
    document = _doc("fr", blocks=[{"title": "Notes", "text": "Livraison. " * 3000}])
    assert render_report_pdf(document, [{"a": "x"}]).startswith(b"%PDF")
