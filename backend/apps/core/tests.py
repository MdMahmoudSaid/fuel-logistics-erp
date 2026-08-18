import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import Product


@pytest.mark.django_db
def test_product_str():
    # "Gasoil"/"Essence" are seeded by migration — use a third product here
    # so the unique `code` constraint doesn't collide with seed data.
    product = Product.objects.create(name="Diesel Premium", code="diesel-premium")
    assert str(product) == "Diesel Premium"


@pytest.mark.django_db
def test_product_api_requires_auth():
    client = APIClient()
    response = client.get("/api/products/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_product_seed_data_present_after_migration():
    assert Product.objects.filter(code="gasoil", name="Gasoil").exists()
    assert Product.objects.filter(code="essence", name="Essence").exists()


@pytest.mark.django_db
def test_product_api_crud_authenticated():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(email="ops@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)

    create_response = client.post(
        "/api/products/", {"name": "Diesel Premium", "code": "diesel-premium"}
    )
    assert create_response.status_code == 201

    list_response = client.get("/api/products/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 3  # 2 seeded (Gasoil, Essence) + 1 created

    detail_response = client.get(f"/api/products/{create_response.data['id']}/")
    assert detail_response.status_code == 200
    assert detail_response.data["code"] == "diesel-premium"

    update_response = client.patch(
        f"/api/products/{create_response.data['id']}/", {"is_active": False}
    )
    assert update_response.status_code == 200
    assert update_response.data["is_active"] is False


@pytest.mark.django_db
def test_product_create_denied_without_operations_permission():
    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(email="fin@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)

    response = client.post("/api/products/", {"name": "Diesel Premium", "code": "diesel-premium"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_product_list_readable_by_a_role_scoped_only_to_purchasing():
    # Regression test for a gap the Phase 2 Section 3.B manual UAT run
    # caught: a role holding only "purchasing" rights (no "operations")
    # couldn't load the product dropdown when creating a SupplierOrder,
    # because ProductViewSet.list was gated entirely behind "operations".
    role = Role.objects.create(name="Purchasing Only", permissions={"purchasing": ["view", "create"]})
    user = User.objects.create_user(email="purchasing-only@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)

    list_response = client.get("/api/products/")
    assert list_response.status_code == 200
    assert list_response.data["count"] >= 2  # at least the seeded Gasoil/Essence

    # Writes remain operations-only even for this role.
    create_response = client.post("/api/products/", {"name": "Kerosene", "code": "kerosene"})
    assert create_response.status_code == 403
