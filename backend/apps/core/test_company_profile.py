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


@pytest.mark.django_db
def test_several_phones_and_emails_are_stored_one_per_line_and_printed_one_per_line():
    client = _client("CPMULTI")
    response = client.patch(
        "/api/settings/company/",
        {
            "address": "IMMEUBLE BAMA", "city": "BKO",
            "phone": "76680484\n 66112233 \n76680484\n\n+22370000000",
            "email": "a@example.com\nb@example.com",
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["phone"] == "76680484\n66112233\n+22370000000"  # blanks / duplicates dropped
    assert response.data["email"] == "a@example.com\nb@example.com"

    contact = CompanyProfile.load().pdf_company()["contact"]
    assert contact == [
        "IMMEUBLE BAMA, BKO",
        "Tél. : (+223) 76680484 · (+223) 66112233",
        "+22370000000",
        "a@example.com",
        "b@example.com",
    ]


@pytest.mark.django_db
def test_legacy_slash_separated_values_are_split_when_read_and_printed():
    CompanyProfile.objects.update_or_create(
        pk=1, defaults={"email": "babaould2020@gmail.com/abdoulkadrisahelcommerce@gmail.com", "phone": "76680484 / 66112233"}
    )
    data = _client("CPLEG").get("/api/settings/company/").data
    assert data["email"] == "babaould2020@gmail.com\nabdoulkadrisahelcommerce@gmail.com"
    assert data["phone"] == "76680484\n66112233"
    contact = CompanyProfile.load().pdf_company()["contact"]
    assert "babaould2020@gmail.com" in contact and "abdoulkadrisahelcommerce@gmail.com" in contact


@pytest.mark.django_db
def test_too_many_contact_values_are_rejected():
    response = _client("CPMAX").patch(
        "/api/settings/company/", {"email": "\n".join(f"u{i}@x.com" for i in range(11))}, format="json"
    )
    assert response.status_code == 400
