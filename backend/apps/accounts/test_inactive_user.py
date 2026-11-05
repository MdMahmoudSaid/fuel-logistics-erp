import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


def _user(**kwargs):
    return User.objects.create_user(
        phone="+2227770001", pin="1234", role=Role.objects.get(name=Role.NAME_ADMIN), **kwargs
    )


@pytest.mark.django_db
def test_inactive_user_cannot_log_in():
    _user(is_active=False)
    resp = APIClient().post(
        "/api/auth/login/", {"phone": "+2227770001", "pin": "1234"}, format="json"
    )
    assert resp.status_code == 401
    assert "access" not in resp.data


@pytest.mark.django_db
def test_deactivating_a_logged_in_user_cuts_their_access_and_refresh():
    user = _user()
    client = APIClient()
    login = client.post("/api/auth/login/", {"phone": "+2227770001", "pin": "1234"}, format="json")
    assert login.status_code == 200

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    assert client.get("/api/customers/").status_code == 200

    user.is_active = False
    user.save(update_fields=["is_active"])

    assert client.get("/api/customers/").status_code == 401
    refresh = APIClient().post("/api/auth/refresh/", {"refresh": login.data["refresh"]}, format="json")
    assert refresh.status_code == 401
