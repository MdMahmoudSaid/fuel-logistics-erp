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
