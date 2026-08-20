# AuditLogViewSet tests (docs/PHASE_6_PLAN.md Etape 5).

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.core.models import Product
from apps.purchasing.models import SupplierOrder
from apps.suppliers.models import Supplier


def _make_admin(suffix):
    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    return User.objects.create_user(
        email=f"admin-auditview-{suffix}@example.com", password="testpass123", role=admin_role
    )


def _make_supplier_order(suffix, admin_user):
    product = Product.objects.get(code="gasoil")
    supplier = Supplier.objects.create(name=f"Supplier {suffix}", country="Senegal")
    order = SupplierOrder.objects.create(
        reference=f"SO-AUDITVIEW-{suffix}",
        supplier=supplier,
        product=product,
        purchase_date="2026-08-18",
        quantity_litres=Decimal("500000.00"),
        unit_price=Decimal("600.0000"),
        created_by=admin_user,
    )
    return order


@pytest.mark.django_db
def test_admin_can_list_audit_logs_filtered_by_object():
    admin_user = _make_admin("LIST")
    order = _make_supplier_order("LIST", admin_user)

    client = APIClient()
    client.force_authenticate(admin_user)
    content_type_id = ContentType.objects.get_for_model(SupplierOrder).id
    response = client.get(
        "/api/audit-logs/", {"content_type": content_type_id, "object_id": order.id}
    )

    assert response.status_code == 200, response.data
    results = response.data["results"] if "results" in response.data else response.data
    assert len(results) == 1
    assert results[0]["action"] == "CREATE"
    assert results[0]["object_id"] == order.id


@pytest.mark.django_db
def test_audit_log_endpoint_is_read_only():
    admin_user = _make_admin("READONLY")
    order = _make_supplier_order("READONLY", admin_user)
    content_type_id = ContentType.objects.get_for_model(SupplierOrder).id

    client = APIClient()
    client.force_authenticate(admin_user)
    list_response = client.get(
        "/api/audit-logs/", {"content_type": content_type_id, "object_id": order.id}
    )
    log_id = (
        list_response.data["results"][0]["id"]
        if "results" in list_response.data
        else list_response.data[0]["id"]
    )

    response = client.delete(f"/api/audit-logs/{log_id}/")
    # ReadOnlyModelViewSet never maps DELETE to a handler, so HasModulePermission
    # sees view.action=None and denies first (403) rather than letting DRF's
    # http_method_not_allowed (405) run - either way, the delete never happens.
    assert response.status_code in (403, 405)
    assert AuditLog.objects.filter(pk=log_id).exists()


@pytest.mark.django_db
def test_non_admin_role_cannot_list_audit_logs():
    role = Role.objects.create(name="NoAdmin", permissions={"reports": ["view"]})
    user = User.objects.create_user(email="no-admin@example.com", password="testpass123", role=role)

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/audit-logs/")

    assert response.status_code == 403
