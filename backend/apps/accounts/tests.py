import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


@pytest.mark.django_db
def test_seed_roles_exist_with_expected_permissions():
    admin = Role.objects.get(name=Role.NAME_ADMIN)
    management = Role.objects.get(name=Role.NAME_MANAGEMENT)
    operations = Role.objects.get(name=Role.NAME_OPERATIONS)
    finance = Role.objects.get(name=Role.NAME_FINANCE)

    assert admin.has_permission("admin", "edit")
    assert admin.has_permission("finance", "cancel")

    assert management.has_permission("sales", "view")
    assert not management.has_permission("sales", "create")
    assert not management.has_permission("admin", "view")

    assert operations.has_permission("operations", "create")
    assert not operations.has_permission("finance", "view")

    assert finance.has_permission("finance", "validate")
    assert not finance.has_permission("admin", "view")


@pytest.mark.django_db
def test_user_role_optional_at_db_level():
    user = User.objects.create_user(phone="+22212345610", pin="1234")
    assert user.role is None


@pytest.mark.django_db
def test_new_user_is_not_locked_by_default():
    user = User.objects.create_user(phone="+22212345611", pin="1234")
    assert user.is_locked() is False


@pytest.mark.django_db
def test_user_is_locked_when_locked_until_in_future():
    from datetime import timedelta

    from django.utils import timezone

    user = User.objects.create_user(phone="+22212345612", pin="1234")
    user.locked_until = timezone.now() + timedelta(minutes=5)
    user.save()
    assert user.is_locked() is True


@pytest.mark.django_db
def test_role_has_permission_unknown_module_returns_false():
    role = Role.objects.create(name="Custom", permissions={"operations": ["view"]})
    assert not role.has_permission("finance", "view")
    assert role.has_permission("operations", "view")


@pytest.mark.django_db
def test_me_endpoint_includes_role_detail():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(phone="+22212345613", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/accounts/users/me/")

    assert response.status_code == 200
    assert response.data["role_detail"]["name"] == "Operations"
    assert "operations" in response.data["role_detail"]["permissions"]


@pytest.mark.django_db
def test_non_admin_cannot_list_users():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(phone="+22212345614", pin="1234", role=role)
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/accounts/users/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_create_user_and_role_endpoints_work():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin = User.objects.create_user(phone="+22212345615", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin)

    create_response = client.post(
        "/api/accounts/users/",
        {
            "phone": "+22212345699",
            "pin": "5678",
            "full_name": "New Hire",
            "role": admin_role.id,
        },
    )
    assert create_response.status_code == 201
    assert User.objects.filter(phone="+22212345699").exists()

    roles_response = client.get("/api/accounts/roles/")
    assert roles_response.status_code == 200
    assert roles_response.data["count"] == 4


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_pin", ["123", "12345", "abcd", "12a4"])
def test_admin_cannot_create_user_with_invalid_pin(invalid_pin):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin = User.objects.create_user(phone="+22212345616", pin="1234", role=admin_role)
    client = APIClient()
    client.force_authenticate(admin)

    create_response = client.post(
        "/api/accounts/users/",
        {
            "phone": "+22212345698",
            "pin": invalid_pin,
            "full_name": "Weak Pin",
            "role": admin_role.id,
        },
    )
    assert create_response.status_code == 400
    assert "pin" in create_response.data
    assert not User.objects.filter(phone="+22212345698").exists()


@pytest.mark.django_db
def test_pin_validator_accepts_four_digits():
    validate_password("1234")


@pytest.mark.parametrize("bad_pin", ["123", "12345", "abcd", "12a4", ""])
def test_pin_validator_rejects_invalid_pin(bad_pin):
    with pytest.raises(DjangoValidationError):
        validate_password(bad_pin)


@pytest.mark.django_db
def test_login_with_phone_and_pin_returns_tokens():
    User.objects.create_user(phone="+22212300001", pin="1234")
    client = APIClient()

    response = client.post("/api/auth/login/", {"phone": "+22212300001", "pin": "1234"})

    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data


@pytest.mark.django_db
def test_login_with_wrong_pin_returns_401():
    User.objects.create_user(phone="+22212300002", pin="1234")
    client = APIClient()

    response = client.post("/api/auth/login/", {"phone": "+22212300002", "pin": "0000"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_token_refresh_issues_new_access_token():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    User.objects.create_user(phone="+22212345617", pin="1234", role=role)
    client = APIClient()

    login = client.post("/api/auth/login/", {"phone": "+22212345617", "pin": "1234"})
    refresh_response = client.post("/api/auth/refresh/", {"refresh": login.data["refresh"]})

    assert refresh_response.status_code == 200
    assert "access" in refresh_response.data


@pytest.mark.django_db
def test_account_locks_after_five_failed_pin_attempts():
    User.objects.create_user(phone="+22212345618", pin="1234")
    client = APIClient()

    for _ in range(5):
        response = client.post("/api/auth/login/", {"phone": "+22212345618", "pin": "0000"})
        assert response.status_code == 401

    locked_out = client.post("/api/auth/login/", {"phone": "+22212345618", "pin": "1234"})
    assert locked_out.status_code == 401

    user = User.objects.get(phone="+22212345618")
    assert user.locked_until is not None


@pytest.mark.django_db
def test_successful_login_resets_failed_pin_attempts():
    user = User.objects.create_user(phone="+22212345619", pin="1234")
    client = APIClient()

    client.post("/api/auth/login/", {"phone": "+22212345619", "pin": "0000"})
    user.refresh_from_db()
    assert user.failed_pin_attempts == 1

    success = client.post("/api/auth/login/", {"phone": "+22212345619", "pin": "1234"})
    assert success.status_code == 200

    user.refresh_from_db()
    assert user.failed_pin_attempts == 0
    assert user.locked_until is None
