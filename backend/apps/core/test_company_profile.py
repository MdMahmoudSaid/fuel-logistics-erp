import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import CompanyProfile


def _client(suffix="CPROF"):
    user = User.objects.create_user(
        phone=f"+222{suffix}", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN)
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_empty_profile_falls_back_to_default_name():
    info = CompanyProfile.load().pdf_company()
    assert info["name"] == "AZUR ÉNERGIE"
    assert info["lines"] == []
    assert info["banks"] == []


@pytest.mark.django_db
def test_patch_profile_and_banks():
    client = _client()
    response = client.patch(
        "/api/settings/company/",
        {
            "name": "Sahel Commerce",
            "tax_id": "071002548J",
            "phone": "76 68 04 84",
            "bank_accounts": [
                {"bank": "ECOBANK", "swift": "ECOCSNDA", "account_number": "SN094 01001"}
            ],
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["bank_accounts"][0]["bank"] == "ECOBANK"
    info = CompanyProfile.load().pdf_company()
    assert info["name"] == "Sahel Commerce"
    assert "NIF : 071002548J" in info["lines"]
    assert info["banks"] == [{"bank": "ECOBANK", "swift": "ECOCSNDA", "account": "SN094 01001"}]

    # A later PATCH without bank_accounts keeps them; with [] clears them.
    client.patch("/api/settings/company/", {"city": "Bamako"}, format="json")
    assert CompanyProfile.load().bank_accounts.count() == 1
    client.patch("/api/settings/company/", {"bank_accounts": []}, format="json")
    assert CompanyProfile.load().bank_accounts.count() == 0
