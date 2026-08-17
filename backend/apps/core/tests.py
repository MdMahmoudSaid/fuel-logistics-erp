import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import Product


@pytest.mark.django_db
def test_product_str():
    product = Product.objects.create(name="Gasoil", code="gasoil")
    assert str(product) == "Gasoil"


@pytest.mark.django_db
def test_product_api_requires_auth():
    client = APIClient()
    response = client.get("/api/products/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_product_api_crud_authenticated():
    user = User.objects.create_user(email="ops@example.com", password="testpass123")
    client = APIClient()
    client.force_authenticate(user)

    create_response = client.post(
        "/api/products/", {"name": "Essence", "code": "essence"}
    )
    assert create_response.status_code == 201

    list_response = client.get("/api/products/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
