import pytest

from apps.core import brand


@pytest.mark.parametrize("key", sorted(brand.BRANDS))
def test_every_brand_has_a_name_and_an_existing_logo(key):
    entry = brand.BRANDS[key]
    assert entry["name"]
    assert entry["logo"].is_file()


def test_default_brand_is_azur_and_feeds_the_pdf_header():
    from apps.reports.services import pdf_template

    assert brand.BRAND_KEY == "azur"
    assert pdf_template.DEFAULT_COMPANY_NAME == "AZUR ÉNERGIE"
    assert pdf_template.LOGO_PATH == brand.BRANDS["azur"]["logo"]


def test_unknown_brand_is_refused(monkeypatch):
    import importlib

    monkeypatch.setenv("BRAND", "nope")
    with pytest.raises(RuntimeError):
        importlib.reload(brand)
    monkeypatch.delenv("BRAND")
    importlib.reload(brand)


def test_sahel_brand_switches_name_and_logo(monkeypatch):
    import importlib

    monkeypatch.setenv("BRAND", "sahel")
    importlib.reload(brand)
    try:
        assert brand.BRAND_NAME == "SAHEL COMMERCE"
        assert brand.BRAND_LOGO_PATH.name == "sahel-commerce-icon.png"
    finally:
        monkeypatch.delenv("BRAND")
        importlib.reload(brand)
