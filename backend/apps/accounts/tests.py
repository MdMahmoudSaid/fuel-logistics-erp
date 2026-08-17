import pytest

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
    user = User.objects.create_user(email="noone@example.com", password="testpass123")
    assert user.role is None


@pytest.mark.django_db
def test_role_has_permission_unknown_module_returns_false():
    role = Role.objects.create(name="Custom", permissions={"operations": ["view"]})
    assert not role.has_permission("finance", "view")
    assert role.has_permission("operations", "view")


from rest_framework.test import APIClient


@pytest.mark.django_db
def test_me_endpoint_includes_role_detail():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(email="ops@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/accounts/users/me/")

    assert response.status_code == 200
    assert response.data["role_detail"]["name"] == "Operations"
    assert "operations" in response.data["role_detail"]["permissions"]


@pytest.mark.django_db
def test_non_admin_cannot_list_users():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(email="ops2@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/accounts/users/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_create_user_and_role_endpoints_work():
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin = User.objects.create_user(
        email="admin@example.com", password="testpass123", role=admin_role
    )
    client = APIClient()
    client.force_authenticate(admin)

    create_response = client.post(
        "/api/accounts/users/",
        {
            "email": "newhire@example.com",
            "password": "testpass123",
            "full_name": "New Hire",
            "role": admin_role.id,
        },
    )
    assert create_response.status_code == 201
    assert User.objects.filter(email="newhire@example.com").exists()

    roles_response = client.get("/api/accounts/roles/")
    assert roles_response.status_code == 200
    assert roles_response.data["count"] == 4


@pytest.mark.django_db
def test_login_with_valid_and_invalid_credentials():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    User.objects.create_user(email="login@example.com", password="testpass123", role=role)
    client = APIClient()

    valid = client.post(
        "/api/auth/login/", {"email": "login@example.com", "password": "testpass123"}
    )
    assert valid.status_code == 200
    assert "access" in valid.data and "refresh" in valid.data

    invalid = client.post(
        "/api/auth/login/", {"email": "login@example.com", "password": "wrong-password"}
    )
    assert invalid.status_code == 401


@pytest.mark.django_db
def test_token_refresh_issues_new_access_token():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    User.objects.create_user(email="refresh@example.com", password="testpass123", role=role)
    client = APIClient()

    login = client.post(
        "/api/auth/login/", {"email": "refresh@example.com", "password": "testpass123"}
    )
    refresh_response = client.post("/api/auth/refresh/", {"refresh": login.data["refresh"]})

    assert refresh_response.status_code == 200
    assert "access" in refresh_response.data
