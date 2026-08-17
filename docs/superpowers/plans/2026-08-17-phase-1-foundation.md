# Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 1 of the ERP: role-based permissions and full CRUD (backend + frontend) for every master-data entity — users, roles, products, suppliers, customers, transporters, drivers, trucks, bank accounts, cash accounts.

**Architecture:** Django/DRF backend adds a `Role` model (JSON permission matrix keyed by module × action) and a shared `HasModulePermission` DRF permission class that every ViewSet declares a `module` for. Each master-data entity gets its own small Django app slice (model + serializer + ModelViewSet + router). The Vue frontend adds a schema-driven `MasterDataView` component (table + modal form) so each entity's UI is a ~20-line field-schema config, plus a bespoke permission-matrix editor for Roles.

**Tech Stack:** Django 5 / DRF / drf-simplejwt / PostgreSQL (backend, already scaffolded); Vue 3 / TypeScript / Pinia / vue-router / Tailwind (frontend, already scaffolded).

**Spec:** `roadmap/phase_1_foundation.md` (implements `docs/ERP_Specification.md` §4, §8–10, §18, §28, §38).

## Global Constraints

- All monetary and litre-quantity fields use `DecimalField`, never float/int (spec §5).
- Single operating currency: `XOF` only in V1 — `currency` fields are a fixed one-choice field (`choices=[("XOF", "XOF")]`), not free text.
- Driver has no required fields except `name` (spec §10) — a missing driver must never block operations.
- Write access is gated by `Role` permission flags via the shared `HasModulePermission` class — never a per-view hardcoded `if request.user.role == ...` check.
- `Truck.status` defaults to `AVAILABLE`; Phase 3 is the only phase allowed to transition it automatically via trip creation.
- This is pre-release scaffold code with no deployed data anywhere — Task 1 deliberately resets the `accounts` migration history rather than writing a data-preserving migration, since there is nothing to preserve yet.

---

## File Structure

**Backend — new/modified per app:**
- `apps/accounts/models.py` — add `Role`, change `User.role` from CharField to FK
- `apps/accounts/migrations/0001_initial.py` — regenerated (Role + User together)
- `apps/accounts/migrations/0002_seed_roles.py` — data migration, 4 seed roles
- `apps/accounts/permissions.py` — new: `HasModulePermission`
- `apps/accounts/serializers.py` — add `RoleSerializer`, update `UserSerializer`
- `apps/accounts/views.py` — add `RoleViewSet`, update `UserViewSet`
- `apps/accounts/urls.py` — register `roles`
- `apps/accounts/tests.py` — new
- `apps/core/views.py` — retrofit `ProductViewSet` with `HasModulePermission`
- `apps/core/migrations/0002_seed_products.py` — data migration, seeds Gasoil/Essence
- `apps/core/tests.py` — update existing tests for the new role requirement and seed data
- `apps/suppliers/{models,serializers,views,urls,tests}.py`
- `apps/customers/{models,serializers,views,urls,tests}.py`
- `apps/transport/{models,serializers,views,urls,tests}.py` — Transporter, Driver, Truck (all live in the existing `transport` app)
- `apps/finance/{models,serializers,views,urls,tests}.py` — BankAccount, CashAccount

**Frontend — new:**
- `src/api/resource.ts` — generic CRUD client factory
- `src/components/master-data/types.ts` — `FieldSchema` type (incl. `password`)
- `src/components/master-data/DataTable.vue`
- `src/components/master-data/EntityForm.vue`
- `src/components/master-data/MasterDataView.vue`
- `src/components/master-data/__tests__/MasterDataView.spec.ts`
- `src/components/master-data/__tests__/EntityForm.spec.ts`
- `src/modules/{products,suppliers,customers,transporters,drivers,trucks}/*View.vue`, `src/modules/finance/{BankAccountView,CashAccountView}.vue` — thin per-entity `MasterDataView` configs
- `src/modules/shell/DashboardPlaceholder.vue` — placeholder for the `/` route until Phase 6 builds the real dashboard
- `src/modules/master-data/__tests__/masterDataViews.spec.ts` — smoke test across all 9 thin wrappers (8 entities + Users)
- `src/modules/users/UserView.vue` — thin `MasterDataView` config (flat fields, incl. a raw numeric `role` ID field)
- `src/modules/roles/permissionSchema.ts` — `MODULES`/`ACTIONS` constants mirroring `Role.MODULES`/`Role.ACTIONS`
- `src/modules/roles/RoleFormModal.vue` — bespoke permission-matrix editor (not a `MasterDataView` config, since `permissions` isn't a flat field)
- `src/modules/roles/RoleListView.vue`
- `src/modules/roles/__tests__/RoleFormModal.spec.ts`
- `src/modules/shell/__tests__/AppShell.spec.ts`

**Frontend — modified:**
- `src/stores/auth.ts` — `User` type gains `role: number | null` and `role_detail`, add `can(module, action)` getter
- `src/stores/__tests__/auth.spec.ts` — add `can()` tests
- `src/router/index.ts` — restructure `AppShell` into a layout with nested `children` routes; register all 10 master-data routes
- `src/modules/shell/AppShell.vue` — rewritten as a layout: sidebar nav (role-filtered via `auth.can`) + `<router-view />`

---

## Task 1: Role model, permission infrastructure, User FK migration

**Files:**
- Modify: `backend/apps/accounts/models.py`
- Create: `backend/apps/accounts/permissions.py`
- Delete + regenerate: `backend/apps/accounts/migrations/0001_initial.py`
- Create: `backend/apps/accounts/migrations/0002_seed_roles.py`
- Create: `backend/apps/accounts/tests.py`

**Interfaces:**
- Produces: `Role` model with `name: str`, `permissions: dict[str, list[str]]`, method `has_permission(module: str, action: str) -> bool`; class constants `Role.MODULES = ["operations", "finance", "sales", "purchasing", "admin"]`, `Role.ACTIONS = ["view", "create", "edit", "validate", "cancel", "export"]`; `Role.NAME_ADMIN/NAME_MANAGEMENT/NAME_OPERATIONS/NAME_FINANCE` string constants matching the seeded row names.
- Produces: `User.role` is now `ForeignKey(Role, null=True, blank=True, on_delete=PROTECT, related_name="users")`.
- Produces: `apps.accounts.permissions.HasModulePermission` — a DRF `BasePermission`; ViewSets set a class attribute `module = "<one of Role.MODULES>"` and get view-action → permission-action mapping for free.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/accounts/tests.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python manage.py test apps.accounts -v 2` (or `pytest apps/accounts/tests.py -v` once deps are installed)
Expected: FAIL — `ImportError: cannot import name 'Role' from 'apps.accounts.models'`

- [ ] **Step 3: Write the Role model and update User**

Replace `backend/apps/accounts/models.py` entirely:

```python
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.core.models import TimeStampedModel

from .managers import UserManager


class Role(TimeStampedModel):
    """Per-module permission matrix (§38). `permissions` shape:
    {"operations": ["view", "create", "edit"], "finance": ["view"], ...}
    A JSON matrix (rather than 30 boolean columns) so new modules can be
    added without a migration and the frontend can render one checkbox
    grid straight off `MODULES` x `ACTIONS`.
    """

    MODULES = ["operations", "finance", "sales", "purchasing", "admin"]
    ACTIONS = ["view", "create", "edit", "validate", "cancel", "export"]

    NAME_ADMIN = "Admin"
    NAME_MANAGEMENT = "Management"
    NAME_OPERATIONS = "Operations"
    NAME_FINANCE = "Finance"

    name = models.CharField(max_length=50, unique=True)
    permissions = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def has_permission(self, module: str, action: str) -> bool:
        return action in self.permissions.get(module, [])


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Custom user, email-based login (§38)."""

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self) -> str:
        return self.email
```

- [ ] **Step 4: Reset and regenerate the accounts migration**

No real data exists anywhere for this pre-release scaffold, so reset rather than write a data-preserving migration:

```bash
cd backend
rm apps/accounts/migrations/0001_initial.py
python manage.py makemigrations accounts
```
Expected output: `Migrations for 'accounts': apps/accounts/migrations/0001_initial.py - Create model Role - Create model User`

- [ ] **Step 5: Write the seed-roles data migration**

Create `backend/apps/accounts/migrations/0002_seed_roles.py`:

```python
from django.db import migrations

ROLES = [
    {
        "name": "Admin",
        "permissions": {
            "operations": ["view", "create", "edit", "validate", "cancel", "export"],
            "finance": ["view", "create", "edit", "validate", "cancel", "export"],
            "sales": ["view", "create", "edit", "validate", "cancel", "export"],
            "purchasing": ["view", "create", "edit", "validate", "cancel", "export"],
            "admin": ["view", "create", "edit", "validate", "cancel", "export"],
        },
    },
    {
        "name": "Management",
        "permissions": {
            "operations": ["view", "export"],
            "finance": ["view", "export"],
            "sales": ["view", "export"],
            "purchasing": ["view", "export"],
        },
    },
    {
        "name": "Operations",
        "permissions": {
            "operations": ["view", "create", "edit"],
            "sales": ["view"],
            "purchasing": ["view"],
        },
    },
    {
        "name": "Finance",
        "permissions": {
            "finance": ["view", "create", "edit", "validate", "export"],
            "operations": ["view"],
            "sales": ["view"],
            "purchasing": ["view"],
        },
    },
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for entry in ROLES:
        Role.objects.update_or_create(
            name=entry["name"], defaults={"permissions": entry["permissions"]}
        )


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(name__in=[r["name"] for r in ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(seed_roles, unseed_roles)]
```

- [ ] **Step 6: Write the HasModulePermission class**

Create `backend/apps/accounts/permissions.py`:

```python
from rest_framework.permissions import BasePermission

ACTION_MAP = {
    "list": "view",
    "retrieve": "view",
    "create": "create",
    "update": "edit",
    "partial_update": "edit",
    "destroy": "cancel",
}


class HasModulePermission(BasePermission):
    """Gate ViewSet actions by the caller's Role permission matrix.

    Set `module = "<one of Role.MODULES>"` as a class attribute on any
    ViewSet using this permission class. Superusers bypass the check.
    """

    module: str | None = None

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        module = getattr(view, "module", self.module)
        action = ACTION_MAP.get(view.action, view.action)

        role = request.user.role
        if role is None or module is None:
            return False
        return role.has_permission(module, action)
```

- [ ] **Step 7: Run migrations and tests, verify pass**

```bash
cd backend
python manage.py migrate
pytest apps/accounts/tests.py -v
```
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/accounts/
git commit -m "feat(accounts): add Role model, permission matrix, HasModulePermission"
```

---

## Task 2: Role/User API endpoints, retrofit Product permissions

**Files:**
- Modify: `backend/apps/accounts/serializers.py`
- Modify: `backend/apps/accounts/views.py`
- Modify: `backend/apps/accounts/urls.py`
- Modify: `backend/apps/accounts/tests.py`
- Modify: `backend/apps/core/views.py`
- Modify: `backend/apps/core/tests.py`
- Create: `backend/apps/core/migrations/0002_seed_products.py` (data migration)

**Interfaces:**
- Consumes: `Role`, `User`, `HasModulePermission` from Task 1.
- Produces: `GET/POST /api/accounts/roles/`, `GET/PATCH /api/accounts/roles/{id}/`; `GET/POST /api/accounts/users/` (module `admin`), `GET /api/accounts/users/me/` (any authenticated user, includes `role_detail`); `ProductViewSet.module = "operations"`; seeded `Product` rows `Gasoil` (code `gasoil`) and `Essence` (code `essence`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/accounts/tests.py`:

```python
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
```

Update `backend/apps/core/tests.py` — the two existing authenticated-flow tests need an explicit role now that `User.role` has no default, and a data migration (Step 6 below) will seed `Gasoil`/`Essence` so the fixture data and expected counts change accordingly:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest apps/accounts/tests.py apps/core/tests.py -v`
Expected: FAIL — `role` is an unexpected keyword to `create_user` isn't the issue (kwargs pass through to the model), but `role_detail` missing from response, `/roles/` 404, and permission tests fail because `ProductViewSet` has no module-based gating yet.

- [ ] **Step 3: Implement serializers**

Replace `backend/apps/accounts/serializers.py`:

```python
from rest_framework import serializers

from .models import Role, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "permissions", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_permissions(self, value):
        for module, actions in value.items():
            if module not in Role.MODULES:
                raise serializers.ValidationError(f"Unknown module: {module}")
            unknown_actions = set(actions) - set(Role.ACTIONS)
            if unknown_actions:
                raise serializers.ValidationError(f"Unknown actions: {unknown_actions}")
        return value


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    role_detail = RoleSerializer(source="role", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "role_detail",
            "is_active",
            "password",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user
```

- [ ] **Step 4: Implement views**

Replace `backend/apps/accounts/views.py`:

```python
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Role, User
from .permissions import HasModulePermission
from .serializers import RoleSerializer, UserSerializer


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [HasModulePermission]
    module = "admin"


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [HasModulePermission]
    module = "admin"

    def get_permissions(self):
        if self.action == "me":
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
```

- [ ] **Step 5: Register the roles route**

Replace `backend/apps/accounts/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import RoleViewSet, UserViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("roles", RoleViewSet, basename="role")

urlpatterns = router.urls
```

- [ ] **Step 6: Retrofit ProductViewSet**

Replace `backend/apps/core/views.py`:

```python
from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import Product
from .serializers import ProductSerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "operations"
```

- [ ] **Step 7: Write the Product seed data migration**

Create `backend/apps/core/migrations/0002_seed_products.py`:

```python
from django.db import migrations

PRODUCTS = [
    {"name": "Gasoil", "code": "gasoil"},
    {"name": "Essence", "code": "essence"},
]


def seed_products(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    for entry in PRODUCTS:
        Product.objects.update_or_create(code=entry["code"], defaults={"name": entry["name"]})


def unseed_products(apps, schema_editor):
    Product = apps.get_model("core", "Product")
    Product.objects.filter(code__in=[p["code"] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed_products, unseed_products)]
```

- [ ] **Step 8: Run migrations and tests, verify pass**

```bash
cd backend
python manage.py migrate
pytest apps/accounts/tests.py apps/core/tests.py -v
```
Expected: 13 passed (8 in `accounts` — 3 from Task 1 plus 5 added here — and 5 in `core`).

- [ ] **Step 9: Commit**

```bash
git add backend/apps/accounts/ backend/apps/core/
git commit -m "feat(accounts): Role/User API endpoints, gate Product on operations module"
```

---

## Task 3: Supplier CRUD

**Files:**
- Modify: `backend/apps/suppliers/models.py`
- Create: `backend/apps/suppliers/serializers.py`
- Create: `backend/apps/suppliers/views.py`
- Modify: `backend/apps/suppliers/urls.py`
- Create: `backend/apps/suppliers/tests.py`
- Create: `backend/apps/suppliers/migrations/0001_initial.py` (generated)

**Interfaces:**
- Consumes: `apps.core.models.TimeStampedModel`, `apps.accounts.permissions.HasModulePermission`.
- Produces: `Supplier` model (`name, company_name, country, phone, contact_name, notes, is_active`); `GET/POST /api/suppliers/`, `GET/PATCH /api/suppliers/{id}/` gated on module `purchasing`.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/suppliers/tests.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.suppliers.models import Supplier


@pytest.mark.django_db
def test_supplier_str():
    supplier = Supplier.objects.create(name="Total Senegal", country="Senegal")
    assert str(supplier) == "Total Senegal"


@pytest.mark.django_db
def test_supplier_crud_requires_purchasing_permission():
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)  # no purchasing:create
    ops_user = User.objects.create_user(email="ops@example.com", password="testpass123", role=ops_role)
    client = APIClient()
    client.force_authenticate(ops_user)

    denied = client.post("/api/suppliers/", {"name": "Shell Mali", "country": "Mali"})
    assert denied.status_code == 403

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(email="admin@example.com", password="testpass123", role=admin_role)
    client.force_authenticate(admin_user)

    created = client.post("/api/suppliers/", {"name": "Shell Mali", "country": "Mali"})
    assert created.status_code == 201

    listed = client.get("/api/suppliers/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    supplier_id = created.data["id"]
    retrieved = client.get(f"/api/suppliers/{supplier_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Shell Mali"

    updated = client.patch(f"/api/suppliers/{supplier_id}/", {"country": "Senegal"})
    assert updated.status_code == 200
    assert updated.data["country"] == "Senegal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest apps/suppliers/tests.py -v`
Expected: FAIL — `ImportError: cannot import name 'Supplier'`

- [ ] **Step 3: Write the model**

Replace `backend/apps/suppliers/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    country = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 4: Write serializer, view, urls**

Create `backend/apps/suppliers/serializers.py`:

```python
from rest_framework import serializers

from .models import Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "id", "name", "company_name", "country", "phone",
            "contact_name", "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
```

Create `backend/apps/suppliers/views.py`:

```python
from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    filterset_fields = ["is_active", "country"]
    permission_classes = [HasModulePermission]
    module = "purchasing"
```

Replace `backend/apps/suppliers/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import SupplierViewSet

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")

urlpatterns = router.urls
```

- [ ] **Step 5: Generate migration, run tests, verify pass**

```bash
cd backend
python manage.py makemigrations suppliers
python manage.py migrate
pytest apps/suppliers/tests.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/suppliers/
git commit -m "feat(suppliers): add Supplier CRUD gated on purchasing module"
```

---

## Task 4: Customer CRUD

**Files:**
- Modify: `backend/apps/customers/models.py`
- Create: `backend/apps/customers/serializers.py`
- Create: `backend/apps/customers/views.py`
- Modify: `backend/apps/customers/urls.py`
- Create: `backend/apps/customers/tests.py`
- Create: `backend/apps/customers/migrations/0001_initial.py` (generated)

**Interfaces:**
- Consumes: `apps.core.models.TimeStampedModel`, `apps.accounts.permissions.HasModulePermission`.
- Produces: `Customer` model (`name, company_name, phone, address, contact_name, notes, is_active`); `GET/POST /api/customers/`, `GET/PATCH /api/customers/{id}/` gated on module `sales`.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/customers/tests.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.customers.models import Customer


@pytest.mark.django_db
def test_customer_str():
    customer = Customer.objects.create(name="Garage Moderne", address="Bamako")
    assert str(customer) == "Garage Moderne"


@pytest.mark.django_db
def test_customer_crud_requires_sales_create_permission():
    ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)  # sales:view only, no create
    ops_user = User.objects.create_user(email="ops@example.com", password="testpass123", role=ops_role)
    client = APIClient()
    client.force_authenticate(ops_user)

    denied = client.post("/api/customers/", {"name": "Garage Moderne"})
    assert denied.status_code == 403

    listed = client.get("/api/customers/")
    assert listed.status_code == 200  # operations has sales:view

    admin_role = Role.objects.get(name=Role.NAME_ADMIN)
    admin_user = User.objects.create_user(email="admin@example.com", password="testpass123", role=admin_role)
    client.force_authenticate(admin_user)

    created = client.post("/api/customers/", {"name": "Garage Moderne"})
    assert created.status_code == 201

    customer_id = created.data["id"]
    retrieved = client.get(f"/api/customers/{customer_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Garage Moderne"

    updated = client.patch(f"/api/customers/{customer_id}/", {"address": "Bamako"})
    assert updated.status_code == 200
    assert updated.data["address"] == "Bamako"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest apps/customers/tests.py -v`
Expected: FAIL — `ImportError: cannot import name 'Customer'`

- [ ] **Step 3: Write the model**

Replace `backend/apps/customers/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel


class Customer(TimeStampedModel):
    name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 4: Write serializer, view, urls**

Create `backend/apps/customers/serializers.py`:

```python
from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id", "name", "company_name", "phone", "address",
            "contact_name", "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
```

Create `backend/apps/customers/views.py`:

```python
from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "sales"
```

Replace `backend/apps/customers/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")

urlpatterns = router.urls
```

- [ ] **Step 5: Generate migration, run tests, verify pass**

```bash
cd backend
python manage.py makemigrations customers
python manage.py migrate
pytest apps/customers/tests.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/customers/
git commit -m "feat(customers): add Customer CRUD gated on sales module"
```

---

## Task 5: Transporter + Driver CRUD

**Files:**
- Modify: `backend/apps/transport/models.py`
- Create: `backend/apps/transport/serializers.py`
- Create: `backend/apps/transport/views.py`
- Modify: `backend/apps/transport/urls.py`
- Create: `backend/apps/transport/tests.py`
- Create: `backend/apps/transport/migrations/0001_initial.py` (generated)

**Interfaces:**
- Consumes: `apps.core.models.TimeStampedModel`, `apps.accounts.permissions.HasModulePermission`.
- Produces: `Transporter` model (`name, company_name, phone, address, is_active`); `Driver` model (`name` required, `phone, license_number, notes` optional). `GET/POST /api/transporters/`, `/api/drivers/` both gated on module `operations`. Both models importable as `apps.transport.models.Transporter` / `.Driver` — Task 6 (Truck) depends on these exact names.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/transport/tests.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.transport.models import Driver, Transporter


@pytest.mark.django_db
def test_transporter_str():
    transporter = Transporter.objects.create(name="Diallo Transport")
    assert str(transporter) == "Diallo Transport"


@pytest.mark.django_db
def test_driver_creation_with_only_name_succeeds():
    driver = Driver.objects.create(name="Ibrahim Kone")
    assert driver.phone == ""
    assert driver.license_number == ""


@pytest.fixture
def ops_client():
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(email="ops@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_transporter_crud_via_api(ops_client):
    created = ops_client.post("/api/transporters/", {"name": "Diallo Transport"})
    assert created.status_code == 201

    listed = ops_client.get("/api/transporters/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    transporter_id = created.data["id"]
    retrieved = ops_client.get(f"/api/transporters/{transporter_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Diallo Transport"

    updated = ops_client.patch(f"/api/transporters/{transporter_id}/", {"phone": "+223 70 00 00 00"})
    assert updated.status_code == 200
    assert updated.data["phone"] == "+223 70 00 00 00"


@pytest.mark.django_db
def test_driver_crud_via_api_with_only_name(ops_client):
    created = ops_client.post("/api/drivers/", {"name": "Ibrahim Kone"})
    assert created.status_code == 201
    assert created.data["phone"] == ""

    driver_id = created.data["id"]
    retrieved = ops_client.get(f"/api/drivers/{driver_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["name"] == "Ibrahim Kone"

    updated = ops_client.patch(f"/api/drivers/{driver_id}/", {"license_number": "ML-12345"})
    assert updated.status_code == 200
    assert updated.data["license_number"] == "ML-12345"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest apps/transport/tests.py -v`
Expected: FAIL — `ImportError: cannot import name 'Driver'`

- [ ] **Step 3: Write the models**

Replace `backend/apps/transport/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel


class Transporter(TimeStampedModel):
    name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Driver(TimeStampedModel):
    """Optional-by-design (§10): only `name` is required. A missing driver
    must never block truck/trip operations."""

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    license_number = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 4: Write serializers, views, urls**

Create `backend/apps/transport/serializers.py`:

```python
from rest_framework import serializers

from .models import Driver, Transporter


class TransporterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transporter
        fields = [
            "id", "name", "company_name", "phone", "address",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DriverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = [
            "id", "name", "phone", "license_number", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
```

Create `backend/apps/transport/views.py`:

```python
from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import Driver, Transporter
from .serializers import DriverSerializer, TransporterSerializer


class TransporterViewSet(viewsets.ModelViewSet):
    queryset = Transporter.objects.all()
    serializer_class = TransporterSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "operations"


class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer
    permission_classes = [HasModulePermission]
    module = "operations"
```

Replace `backend/apps/transport/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import DriverViewSet, TransporterViewSet

router = DefaultRouter()
router.register("transporters", TransporterViewSet, basename="transporter")
router.register("drivers", DriverViewSet, basename="driver")

urlpatterns = router.urls
```

- [ ] **Step 5: Generate migration, run tests, verify pass**

```bash
cd backend
python manage.py makemigrations transport
python manage.py migrate
pytest apps/transport/tests.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/transport/
git commit -m "feat(transport): add Transporter and Driver CRUD gated on operations module"
```

---

## Task 6: Truck CRUD

**Files:**
- Modify: `backend/apps/transport/models.py` (add `Truck`, alongside `Transporter`/`Driver` from Task 5)
- Modify: `backend/apps/transport/serializers.py`
- Modify: `backend/apps/transport/views.py`
- Modify: `backend/apps/transport/urls.py`
- Modify: `backend/apps/transport/tests.py`
- Create: `backend/apps/transport/migrations/0002_truck.py` (generated)

**Interfaces:**
- Consumes: `Transporter`, `Driver` from Task 5 (same app, same file).
- Produces: `Truck` model (`internal_id` unique, `tractor_registration`, `tanker_registration`, `capacity_litres`, `ownership_type` in `{COMPANY_OWNED, EXTERNAL}`, `owner_transporter` FK nullable, `default_driver` FK nullable, `status` in `{AVAILABLE, ON_TRIP, BLOCKED}` default `AVAILABLE`, `notes`). `GET/POST /api/trucks/` gated on module `operations`.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/transport/tests.py`:

```python
from apps.transport.models import Truck


@pytest.mark.django_db
def test_truck_defaults_to_available_status():
    truck = Truck.objects.create(
        internal_id="TRK-001",
        tractor_registration="AA-123-SN",
        tanker_registration="BB-456-SN",
        capacity_litres="45000.00",
    )
    assert truck.status == Truck.Status.AVAILABLE
    assert truck.owner_transporter is None


@pytest.mark.django_db
def test_truck_crud_via_api(ops_client):
    created = ops_client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-002",
            "tractor_registration": "CC-789-SN",
            "tanker_registration": "DD-012-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert created.status_code == 201
    assert created.data["status"] == "AVAILABLE"

    listed = ops_client.get("/api/trucks/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    truck_id = created.data["id"]
    retrieved = ops_client.get(f"/api/trucks/{truck_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["internal_id"] == "TRK-002"

    updated = ops_client.patch(f"/api/trucks/{truck_id}/", {"notes": "Needs tyre check"})
    assert updated.status_code == 200
    assert updated.data["notes"] == "Needs tyre check"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest apps/transport/tests.py -v`
Expected: FAIL — `ImportError: cannot import name 'Truck'`

- [ ] **Step 3: Add the Truck model**

Append to `backend/apps/transport/models.py`:

```python
class Truck(TimeStampedModel):
    class OwnershipType(models.TextChoices):
        COMPANY_OWNED = "COMPANY_OWNED", "Company owned"
        EXTERNAL = "EXTERNAL", "External / rented"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        ON_TRIP = "ON_TRIP", "On trip"
        BLOCKED = "BLOCKED", "Blocked"

    internal_id = models.CharField(max_length=30, unique=True)
    tractor_registration = models.CharField(max_length=30)
    tanker_registration = models.CharField(max_length=30)
    capacity_litres = models.DecimalField(max_digits=10, decimal_places=2)
    ownership_type = models.CharField(
        max_length=20, choices=OwnershipType.choices, default=OwnershipType.COMPANY_OWNED
    )
    owner_transporter = models.ForeignKey(
        Transporter, null=True, blank=True, on_delete=models.SET_NULL, related_name="trucks"
    )
    default_driver = models.ForeignKey(
        Driver, null=True, blank=True, on_delete=models.SET_NULL, related_name="trucks"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["internal_id"]

    def __str__(self) -> str:
        return self.internal_id
```

- [ ] **Step 4: Add serializer, view, url**

Update the import line at the top of `backend/apps/transport/serializers.py` to `from .models import Driver, Transporter, Truck`, then append:

```python
class TruckSerializer(serializers.ModelSerializer):
    class Meta:
        model = Truck
        fields = [
            "id", "internal_id", "tractor_registration", "tanker_registration",
            "capacity_litres", "ownership_type", "owner_transporter", "default_driver",
            "status", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]
```

Update the import line at the top of `backend/apps/transport/views.py` to `from .models import Driver, Transporter, Truck` and `from .serializers import DriverSerializer, TransporterSerializer, TruckSerializer`, then append:

```python
class TruckViewSet(viewsets.ModelViewSet):
    queryset = Truck.objects.all()
    serializer_class = TruckSerializer
    filterset_fields = ["status", "ownership_type"]
    permission_classes = [HasModulePermission]
    module = "operations"
```

Update `backend/apps/transport/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import DriverViewSet, TransporterViewSet, TruckViewSet

router = DefaultRouter()
router.register("transporters", TransporterViewSet, basename="transporter")
router.register("drivers", DriverViewSet, basename="driver")
router.register("trucks", TruckViewSet, basename="truck")

urlpatterns = router.urls
```

- [ ] **Step 5: Generate migration, run tests, verify pass**

```bash
cd backend
python manage.py makemigrations transport
python manage.py migrate
pytest apps/transport/tests.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/transport/
git commit -m "feat(transport): add Truck CRUD gated on operations module"
```

---

## Task 7: BankAccount + CashAccount CRUD, mandatory cross-module permission test

**Files:**
- Modify: `backend/apps/finance/models.py`
- Create: `backend/apps/finance/serializers.py`
- Create: `backend/apps/finance/views.py`
- Modify: `backend/apps/finance/urls.py`
- Create: `backend/apps/finance/tests.py`
- Create: `backend/apps/finance/migrations/0001_initial.py` (generated)

**Interfaces:**
- Consumes: `apps.core.models.TimeStampedModel`, `apps.accounts.permissions.HasModulePermission`, `apps.transport.models.Truck` (for the cross-module test only).
- Produces: `BankAccount` model (`name, bank_name, account_number, currency, opening_balance, is_active`, `current_balance` property); `CashAccount` model (`name, location, currency, opening_balance, is_active`, `current_balance` property). `GET/POST /api/bank-accounts/`, `/api/cash-accounts/` gated on module `finance`.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/finance/tests.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.finance.models import BankAccount, CashAccount


@pytest.mark.django_db
def test_bank_account_current_balance_defaults_to_opening_balance():
    account = BankAccount.objects.create(
        name="Main BOA Account", bank_name="Bank of Africa", opening_balance="1000000.00"
    )
    # No TreasuryTransaction model exists until Phase 5 — current_balance is
    # opening_balance alone for now, and will sum real transactions later.
    assert account.current_balance == account.opening_balance


@pytest.mark.django_db
def test_cash_account_currency_defaults_to_xof():
    account = CashAccount.objects.create(name="Main Cash", location="Dakar office")
    assert account.currency == "XOF"


@pytest.fixture
def finance_client():
    role = Role.objects.get(name=Role.NAME_FINANCE)
    user = User.objects.create_user(email="fin@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_bank_account_crud_via_api(finance_client):
    created = finance_client.post(
        "/api/bank-accounts/", {"name": "Main BOA Account", "bank_name": "Bank of Africa", "opening_balance": "1000000.00"}
    )
    assert created.status_code == 201

    listed = finance_client.get("/api/bank-accounts/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    account_id = created.data["id"]
    retrieved = finance_client.get(f"/api/bank-accounts/{account_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["current_balance"] == "1000000.00"

    updated = finance_client.patch(f"/api/bank-accounts/{account_id}/", {"account_number": "SN001"})
    assert updated.status_code == 200
    assert updated.data["account_number"] == "SN001"


@pytest.mark.django_db
def test_cash_account_crud_via_api(finance_client):
    created = finance_client.post(
        "/api/cash-accounts/", {"name": "Main Cash", "location": "Dakar office", "opening_balance": "500000.00"}
    )
    assert created.status_code == 201

    listed = finance_client.get("/api/cash-accounts/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1

    account_id = created.data["id"]
    retrieved = finance_client.get(f"/api/cash-accounts/{account_id}/")
    assert retrieved.status_code == 200
    assert retrieved.data["current_balance"] == "500000.00"

    updated = finance_client.patch(f"/api/cash-accounts/{account_id}/", {"location": "Bamako office"})
    assert updated.status_code == 200
    assert updated.data["location"] == "Bamako office"


@pytest.mark.django_db
def test_operations_role_can_create_truck_but_not_bank_account():
    """Mandatory scenario from roadmap/phase_1_foundation.md: an Operations
    user must be able to create a Truck (operations module) but must be
    denied creating a BankAccount (finance module)."""
    role = Role.objects.get(name=Role.NAME_OPERATIONS)
    user = User.objects.create_user(email="ops@example.com", password="testpass123", role=role)
    client = APIClient()
    client.force_authenticate(user)

    truck_response = client.post(
        "/api/trucks/",
        {
            "internal_id": "TRK-100",
            "tractor_registration": "EE-345-SN",
            "tanker_registration": "FF-678-SN",
            "capacity_litres": "45000.00",
            "ownership_type": "COMPANY_OWNED",
        },
    )
    assert truck_response.status_code == 201

    bank_response = client.post(
        "/api/bank-accounts/", {"name": "Main BOA Account", "opening_balance": "1000000.00"}
    )
    assert bank_response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest apps/finance/tests.py -v`
Expected: FAIL — `ImportError: cannot import name 'BankAccount'`

- [ ] **Step 3: Write the models**

Replace `backend/apps/finance/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel

CURRENCY_CHOICES = [("XOF", "XOF")]


class BankAccount(TimeStampedModel):
    name = models.CharField(max_length=150)
    bank_name = models.CharField(max_length=150, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="XOF")
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def current_balance(self):
        # opening_balance + Σ(TreasuryTransaction) once that model exists
        # (Phase 5, roadmap/phase_5_finance.md) — computed, never stored,
        # so it can never drift from the transaction ledger.
        return self.opening_balance


class CashAccount(TimeStampedModel):
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=150, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="XOF")
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def current_balance(self):
        return self.opening_balance
```

- [ ] **Step 4: Write serializers, views, urls**

Create `backend/apps/finance/serializers.py`:

```python
from rest_framework import serializers

from .models import BankAccount, CashAccount


class BankAccountSerializer(serializers.ModelSerializer):
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            "id", "name", "bank_name", "account_number", "currency",
            "opening_balance", "current_balance", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CashAccountSerializer(serializers.ModelSerializer):
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = CashAccount
        fields = [
            "id", "name", "location", "currency",
            "opening_balance", "current_balance", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
```

Create `backend/apps/finance/views.py`:

```python
from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission

from .models import BankAccount, CashAccount
from .serializers import BankAccountSerializer, CashAccountSerializer


class BankAccountViewSet(viewsets.ModelViewSet):
    queryset = BankAccount.objects.all()
    serializer_class = BankAccountSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "finance"


class CashAccountViewSet(viewsets.ModelViewSet):
    queryset = CashAccount.objects.all()
    serializer_class = CashAccountSerializer
    filterset_fields = ["is_active"]
    permission_classes = [HasModulePermission]
    module = "finance"
```

Replace `backend/apps/finance/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import BankAccountViewSet, CashAccountViewSet

router = DefaultRouter()
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("cash-accounts", CashAccountViewSet, basename="cashaccount")

urlpatterns = router.urls
```

- [ ] **Step 5: Generate migration, run tests, verify pass**

```bash
cd backend
python manage.py makemigrations finance
python manage.py migrate
pytest apps/finance/tests.py -v
```
Expected: 5 passed — including `test_operations_role_can_create_truck_but_not_bank_account`, the mandatory permission-boundary test.

- [ ] **Step 6: Run the full backend test suite**

```bash
cd backend
pytest -v
```
Expected: all tests across `accounts`, `core`, `suppliers`, `customers`, `transport`, `finance` pass.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/finance/
git commit -m "feat(finance): add BankAccount/CashAccount CRUD, verify operations/finance permission boundary"
```

---

## Task 8: Shared master-data frontend components

**Files:**
- Create: `frontend/src/api/resource.ts`
- Create: `frontend/src/components/master-data/types.ts`
- Create: `frontend/src/components/master-data/DataTable.vue`
- Create: `frontend/src/components/master-data/EntityForm.vue`
- Create: `frontend/src/components/master-data/MasterDataView.vue`
- Create: `frontend/src/components/master-data/__tests__/MasterDataView.spec.ts`

**Interfaces:**
- Consumes: `apiClient` from `frontend/src/api/client.ts` (already exists).
- Produces: `createResourceApi<T = Record<string, unknown>>(basePath: string): ResourceApi<T>` with `{list, create, update, remove}` — the default type parameter matters: every Task 9/10 thin wrapper calls this without an explicit `<T>`, so it must default to `Record<string, unknown>` to satisfy `MasterDataView`'s prop type; `FieldSchema` type (`key, label, type: 'text'|'number'|'checkbox'|'textarea'|'select', required?, options?`); `MasterDataView` component with props `{title: string, resource: ResourceApi<Record<string, unknown>>, fields: FieldSchema[]}` — this exact prop contract is what every Task 9/10 wrapper view depends on.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/master-data/__tests__/MasterDataView.spec.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import type { FieldSchema } from '@/components/master-data/types'

const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]

function makeResource(initialRows: Record<string, unknown>[]) {
  const rows = [...initialRows]
  return {
    list: vi.fn(async () => ({ count: rows.length, next: null, previous: null, results: rows })),
    create: vi.fn(async (payload: Record<string, unknown>) => {
      const created = { id: rows.length + 1, ...payload }
      rows.push(created)
      return created
    }),
    update: vi.fn(async (id: number, payload: Record<string, unknown>) => {
      const index = rows.findIndex((r) => r.id === id)
      rows[index] = { ...rows[index], ...payload }
      return rows[index]
    }),
    remove: vi.fn(async () => undefined),
  }
}

describe('MasterDataView', () => {
  it('loads and renders rows on mount', async () => {
    const resource = makeResource([{ id: 1, name: 'Total Senegal', is_active: true }])
    const wrapper = mount(MasterDataView, { props: { title: 'Suppliers', resource, fields } })
    await flushPromises()

    expect(resource.list).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Total Senegal')
  })

  it('creates a new record through the Add flow', async () => {
    const resource = makeResource([])
    const wrapper = mount(MasterDataView, { props: { title: 'Suppliers', resource, fields } })
    await flushPromises()

    await wrapper.find('button').trigger('click') // "Add" button
    await wrapper.find('input#name').setValue('Shell Mali')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(resource.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Shell Mali' }))
    expect(wrapper.text()).toContain('Shell Mali')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/master-data`
Expected: FAIL — `Failed to resolve import "@/components/master-data/MasterDataView.vue"`

- [ ] **Step 3: Write the types and resource client**

Create `frontend/src/components/master-data/types.ts`:

```ts
export type FieldType = 'text' | 'number' | 'checkbox' | 'textarea' | 'select'

export interface FieldOption {
  value: string
  label: string
}

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  required?: boolean
  options?: FieldOption[]
}
```

Create `frontend/src/api/resource.ts`:

```ts
import { apiClient } from './client'

export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface ResourceApi<T> {
  list: () => Promise<PaginatedResponse<T>>
  create: (payload: Partial<T>) => Promise<T>
  update: (id: number, payload: Partial<T>) => Promise<T>
  remove: (id: number) => Promise<void>
}

export function createResourceApi<T = Record<string, unknown>>(basePath: string): ResourceApi<T> {
  return {
    list: () => apiClient.get<PaginatedResponse<T>>(basePath).then((r) => r.data),
    create: (payload) => apiClient.post<T>(basePath, payload).then((r) => r.data),
    update: (id, payload) => apiClient.patch<T>(`${basePath}${id}/`, payload).then((r) => r.data),
    remove: (id) => apiClient.delete(`${basePath}${id}/`).then(() => undefined),
  }
}
```

- [ ] **Step 4: Write DataTable and EntityForm**

Create `frontend/src/components/master-data/DataTable.vue`:

```vue
<script setup lang="ts">
defineProps<{
  columns: { key: string; label: string }[]
  rows: Record<string, unknown>[]
}>()

defineEmits<{ edit: [row: Record<string, unknown>] }>()
</script>

<template>
  <table class="w-full text-left text-sm">
    <thead>
      <tr class="border-b text-slate-500">
        <th v-for="col in columns" :key="col.key" class="px-3 py-2 font-medium">{{ col.label }}</th>
        <th class="px-3 py-2" />
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in rows" :key="String(row.id)" class="border-b last:border-0 hover:bg-slate-50">
        <td v-for="col in columns" :key="col.key" class="px-3 py-2">{{ row[col.key] }}</td>
        <td class="px-3 py-2 text-right">
          <button class="text-slate-500 hover:text-slate-800" @click="$emit('edit', row)">Edit</button>
        </td>
      </tr>
      <tr v-if="rows.length === 0">
        <td :colspan="columns.length + 1" class="px-3 py-6 text-center text-slate-400">
          No records yet.
        </td>
      </tr>
    </tbody>
  </table>
</template>
```

Create `frontend/src/components/master-data/EntityForm.vue`:

```vue
<script setup lang="ts">
import type { FieldSchema } from './types'

const props = defineProps<{
  fields: FieldSchema[]
  modelValue: Record<string, unknown>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>]
  submit: []
  cancel: []
}>()

function setField(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <form class="space-y-3" @submit.prevent="$emit('submit')">
    <div v-for="field in fields" :key="field.key" class="space-y-1">
      <label class="text-sm font-medium text-slate-600" :for="field.key">{{ field.label }}</label>

      <input
        v-if="field.type === 'text' || field.type === 'number'"
        :id="field.key"
        :type="field.type"
        :required="field.required"
        :value="modelValue[field.key] as string | number | undefined"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        @input="setField(field.key, ($event.target as HTMLInputElement).value)"
      />

      <textarea
        v-else-if="field.type === 'textarea'"
        :id="field.key"
        :value="modelValue[field.key] as string | undefined"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        rows="3"
        @input="setField(field.key, ($event.target as HTMLTextAreaElement).value)"
      />

      <select
        v-else-if="field.type === 'select'"
        :id="field.key"
        :value="modelValue[field.key] as string | undefined"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        @change="setField(field.key, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>

      <input
        v-else-if="field.type === 'checkbox'"
        :id="field.key"
        type="checkbox"
        :checked="Boolean(modelValue[field.key])"
        @change="setField(field.key, ($event.target as HTMLInputElement).checked)"
      />
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <button type="button" class="px-3 py-2 text-sm text-slate-500" @click="$emit('cancel')">
        Cancel
      </button>
      <button type="submit" class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white">
        Save
      </button>
    </div>
  </form>
</template>
```

- [ ] **Step 5: Write MasterDataView**

Create `frontend/src/components/master-data/MasterDataView.vue`:

```vue
<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import DataTable from './DataTable.vue'
import EntityForm from './EntityForm.vue'
import type { FieldSchema } from './types'
import type { ResourceApi } from '@/api/resource'

const props = defineProps<{
  title: string
  resource: ResourceApi<Record<string, unknown>>
  fields: FieldSchema[]
}>()

const rows = ref<Record<string, unknown>[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const formValue = ref<Record<string, unknown>>({})
const error = ref('')

const columns = computed(() =>
  props.fields.filter((f) => f.type !== 'textarea').map((f) => ({ key: f.key, label: f.label })),
)

async function load() {
  const data = await props.resource.list()
  rows.value = data.results
}

function openCreate() {
  editingId.value = null
  formValue.value = {}
  showForm.value = true
  error.value = ''
}

function openEdit(row: Record<string, unknown>) {
  editingId.value = row.id as number
  formValue.value = { ...row }
  showForm.value = true
  error.value = ''
}

async function onSubmit() {
  try {
    if (editingId.value === null) {
      await props.resource.create(formValue.value)
    } else {
      await props.resource.update(editingId.value, formValue.value)
    }
    showForm.value = false
    await load()
  } catch {
    error.value = 'Could not save — check the fields and your permissions.'
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">{{ title }}</h2>
      <button class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white" @click="openCreate">
        Add
      </button>
    </div>

    <div class="rounded border bg-white">
      <DataTable :columns="columns" :rows="rows" @edit="openEdit" />
    </div>

    <div v-if="showForm" class="fixed inset-0 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h3 class="mb-4 text-base font-semibold text-slate-800">
          {{ editingId === null ? 'New' : 'Edit' }} {{ title }}
        </h3>
        <p v-if="error" class="mb-2 text-sm text-red-600">{{ error }}</p>
        <EntityForm v-model="formValue" :fields="fields" @submit="onSubmit" @cancel="showForm = false" />
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 6: Run tests, verify pass**

```bash
cd frontend
npx vitest run src/components/master-data
```
Expected: 2 passed.

- [ ] **Step 7: Typecheck**

```bash
cd frontend
npx vue-tsc -b
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/resource.ts frontend/src/components/master-data/
git commit -m "feat(frontend): add schema-driven MasterDataView, DataTable, EntityForm"
```

---

## Task 9: Thin wrapper views for the 8 master-data entities

**Files:**
- Create: `frontend/src/modules/products/ProductView.vue`
- Create: `frontend/src/modules/suppliers/SupplierView.vue`
- Create: `frontend/src/modules/customers/CustomerView.vue`
- Create: `frontend/src/modules/transporters/TransporterView.vue`
- Create: `frontend/src/modules/drivers/DriverView.vue`
- Create: `frontend/src/modules/trucks/TruckView.vue`
- Create: `frontend/src/modules/finance/BankAccountView.vue`
- Create: `frontend/src/modules/finance/CashAccountView.vue`
- Create: `frontend/src/modules/master-data/__tests__/masterDataViews.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/modules/shell/AppShell.vue`

**Interfaces:**
- Consumes: `createResourceApi` (Task 8), `MasterDataView`/`FieldSchema` (Task 8).
- Produces: 8 route-mounted views, each a `resource` + `fields` config; nested routing under `AppShell` via `<router-view />` — Task 11 (nav) depends on the route `name`s defined here: `products`, `suppliers`, `customers`, `transporters`, `drivers`, `trucks`, `bank-accounts`, `cash-accounts`.

**Known simplification (documented, not a placeholder):** `Truck.owner_transporter` / `default_driver` are plain numeric PK inputs in this phase, not a searchable picker — building a cross-entity autocomplete is out of scope for Phase 1's master-data CRUD and can be added once Phase 3's trip UI needs the same lookup. `Truck.status` is omitted from the schema entirely since the API marks it read-only (Phase 3 owns status transitions).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/modules/master-data/__tests__/masterDataViews.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import ProductView from '@/modules/products/ProductView.vue'
import SupplierView from '@/modules/suppliers/SupplierView.vue'
import CustomerView from '@/modules/customers/CustomerView.vue'
import TransporterView from '@/modules/transporters/TransporterView.vue'
import DriverView from '@/modules/drivers/DriverView.vue'
import TruckView from '@/modules/trucks/TruckView.vue'
import BankAccountView from '@/modules/finance/BankAccountView.vue'
import CashAccountView from '@/modules/finance/CashAccountView.vue'

const views = [
  ['ProductView', ProductView, 'Products'],
  ['SupplierView', SupplierView, 'Suppliers'],
  ['CustomerView', CustomerView, 'Customers'],
  ['TransporterView', TransporterView, 'Transporters'],
  ['DriverView', DriverView, 'Drivers'],
  ['TruckView', TruckView, 'Trucks'],
  ['BankAccountView', BankAccountView, 'Bank Accounts'],
  ['CashAccountView', CashAccountView, 'Cash Accounts'],
] as const

describe('master-data thin wrapper views', () => {
  it.each(views)(
    '%s renders MasterDataView with the right title and a non-empty field schema',
    (_name, component, expectedTitle) => {
      const wrapper = shallowMount(component, { global: { stubs: { MasterDataView: true } } })
      const masterDataView = wrapper.findComponent(MasterDataView)

      expect(masterDataView.props('title')).toBe(expectedTitle)
      expect((masterDataView.props('fields') as unknown[]).length).toBeGreaterThan(0)
      expect(masterDataView.props('resource')).toBeDefined()
    },
  )
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/modules/master-data`
Expected: FAIL — `Failed to resolve import "@/modules/products/ProductView.vue"`

- [ ] **Step 3: Write the 8 thin wrapper views**

Create `frontend/src/modules/products/ProductView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/products/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'code', label: 'Code', type: 'text', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Products" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/suppliers/SupplierView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/suppliers/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'company_name', label: 'Company', type: 'text' },
  { key: 'country', label: 'Country', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'contact_name', label: 'Contact', type: 'text' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Suppliers" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/customers/CustomerView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/customers/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'company_name', label: 'Company', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'address', label: 'Address', type: 'text' },
  { key: 'contact_name', label: 'Contact', type: 'text' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Customers" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/transporters/TransporterView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/transporters/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'company_name', label: 'Company', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'address', label: 'Address', type: 'text' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Transporters" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/drivers/DriverView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/drivers/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'license_number', label: 'Licence', type: 'text' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
]
</script>

<template>
  <MasterDataView title="Drivers" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/trucks/TruckView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/trucks/')
const fields: FieldSchema[] = [
  { key: 'internal_id', label: 'Internal ID', type: 'text', required: true },
  { key: 'tractor_registration', label: 'Tractor Reg.', type: 'text', required: true },
  { key: 'tanker_registration', label: 'Tanker Reg.', type: 'text', required: true },
  { key: 'capacity_litres', label: 'Capacity (L)', type: 'number', required: true },
  {
    key: 'ownership_type',
    label: 'Ownership',
    type: 'select',
    required: true,
    options: [
      { value: 'COMPANY_OWNED', label: 'Company owned' },
      { value: 'EXTERNAL', label: 'External / rented' },
    ],
  },
  { key: 'owner_transporter', label: 'Owner Transporter ID', type: 'number' },
  { key: 'default_driver', label: 'Default Driver ID', type: 'number' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
]
</script>

<template>
  <MasterDataView title="Trucks" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/finance/BankAccountView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/bank-accounts/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'bank_name', label: 'Bank', type: 'text' },
  { key: 'account_number', label: 'Account Number', type: 'text' },
  { key: 'currency', label: 'Currency', type: 'select', options: [{ value: 'XOF', label: 'XOF' }] },
  { key: 'opening_balance', label: 'Opening Balance', type: 'number', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Bank Accounts" :resource="resource" :fields="fields" />
</template>
```

Create `frontend/src/modules/finance/CashAccountView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/cash-accounts/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'location', label: 'Location', type: 'text' },
  { key: 'currency', label: 'Currency', type: 'select', options: [{ value: 'XOF', label: 'XOF' }] },
  { key: 'opening_balance', label: 'Opening Balance', type: 'number', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Cash Accounts" :resource="resource" :fields="fields" />
</template>
```

- [ ] **Step 4: Turn AppShell into a layout and register nested routes**

Replace `frontend/src/modules/shell/AppShell.vue`'s `<main>` block — keep the existing `<script setup>` and `<header>` unchanged, replace only the `<main>`:

```vue
    <main class="p-6">
      <router-view />
    </main>
```

Replace `frontend/src/router/index.ts`:

```ts
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/modules/auth/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/modules/shell/AppShell.vue'),
      children: [
        { path: '', name: 'home', component: () => import('@/modules/shell/DashboardPlaceholder.vue') },
        { path: 'products', name: 'products', component: () => import('@/modules/products/ProductView.vue') },
        { path: 'suppliers', name: 'suppliers', component: () => import('@/modules/suppliers/SupplierView.vue') },
        { path: 'customers', name: 'customers', component: () => import('@/modules/customers/CustomerView.vue') },
        {
          path: 'transporters',
          name: 'transporters',
          component: () => import('@/modules/transporters/TransporterView.vue'),
        },
        { path: 'drivers', name: 'drivers', component: () => import('@/modules/drivers/DriverView.vue') },
        { path: 'trucks', name: 'trucks', component: () => import('@/modules/trucks/TruckView.vue') },
        {
          path: 'bank-accounts',
          name: 'bank-accounts',
          component: () => import('@/modules/finance/BankAccountView.vue'),
        },
        {
          path: 'cash-accounts',
          name: 'cash-accounts',
          component: () => import('@/modules/finance/CashAccountView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'home' }
  }
  return true
})

export default router
```

Create `frontend/src/modules/shell/DashboardPlaceholder.vue` (the real dashboard is Phase 6 — this keeps `/` non-empty until then):

```vue
<template>
  <p class="text-slate-500">
    Dashboard lands in Phase 6. Use the navigation to manage master data.
  </p>
</template>
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd frontend
npx vitest run
```
Expected: all suites pass, including the new 8-case `masterDataViews.spec.ts`.

- [ ] **Step 6: Typecheck and build**

```bash
cd frontend
npx vue-tsc -b && npx vite build
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/ frontend/src/router/
git commit -m "feat(frontend): add master-data views for all Phase 1 entities and nested routing"
```

---

## Task 10: Users + Roles admin UI

**Files:**
- Modify: `frontend/src/components/master-data/types.ts` (add `'password'` field type)
- Modify: `frontend/src/components/master-data/EntityForm.vue` (render password inputs masked)
- Create: `frontend/src/components/master-data/__tests__/EntityForm.spec.ts`
- Create: `frontend/src/modules/roles/permissionSchema.ts`
- Create: `frontend/src/modules/roles/RoleFormModal.vue`
- Create: `frontend/src/modules/roles/__tests__/RoleFormModal.spec.ts`
- Create: `frontend/src/modules/roles/RoleListView.vue`
- Create: `frontend/src/modules/users/UserView.vue`
- Modify: `frontend/src/modules/master-data/__tests__/masterDataViews.spec.ts` (add `UserView` case)
- Modify: `frontend/src/router/index.ts` (add `users`, `roles` routes)

**Interfaces:**
- Consumes: `MasterDataView`, `FieldSchema`, `createResourceApi` (Task 8).
- Produces: `permissionSchema.ts` exports `MODULES`/`ACTIONS` — must stay in sync with `backend/apps/accounts/models.py`'s `Role.MODULES`/`Role.ACTIONS` from Task 1 (same 5 modules, same 6 actions, same order). `FieldSchema.type` gains `'password'`.

**Known simplification (documented, not a placeholder):** `User.role` is a raw numeric Role-ID input in this phase, matching the same pattern used for `Truck.owner_transporter`/`default_driver` in Task 9 — a live role picker is deferred.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/master-data/__tests__/EntityForm.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EntityForm from '@/components/master-data/EntityForm.vue'
import type { FieldSchema } from '@/components/master-data/types'

describe('EntityForm', () => {
  it('renders a password field as a masked input', () => {
    const fields: FieldSchema[] = [{ key: 'password', label: 'Password', type: 'password' }]
    const wrapper = mount(EntityForm, { props: { fields, modelValue: {} } })

    expect(wrapper.find('input#password').attributes('type')).toBe('password')
  })
})
```

Create `frontend/src/modules/roles/__tests__/RoleFormModal.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import RoleFormModal from '@/modules/roles/RoleFormModal.vue'

describe('RoleFormModal', () => {
  it('toggles a permission action on and off', async () => {
    const wrapper = mount(RoleFormModal, {
      props: { modelValue: { name: 'Custom', permissions: {} } },
    })

    const rows = wrapper.findAll('tbody tr')
    const operationsRow = rows[0]
    await operationsRow!.findAll('input[type="checkbox"]')[0]!.setValue(true)

    let emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0]![0] as { permissions: Record<string, string[]> }).permissions.operations).toEqual([
      'view',
    ])

    await wrapper.setProps({
      modelValue: (emitted[0]![0] as { name: string; permissions: Record<string, string[]> }),
    })
    await wrapper.findAll('tbody tr')[0]!.findAll('input[type="checkbox"]')[0]!.setValue(false)

    emitted = wrapper.emitted('update:modelValue')!
    expect(
      (emitted[emitted.length - 1]![0] as { permissions: Record<string, string[]> }).permissions
        .operations,
    ).toEqual([])
  })
})
```

Update `frontend/src/modules/master-data/__tests__/masterDataViews.spec.ts` — add the import and array entry:

```ts
import UserView from '@/modules/users/UserView.vue'
```

```ts
const views = [
  // ...existing entries...
  ['UserView', UserView, 'Users'],
] as const
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/master-data src/modules/roles src/modules/master-data`
Expected: FAIL — `input#password` has `type="text"` (default), and `Failed to resolve import "@/modules/roles/RoleFormModal.vue"`.

- [ ] **Step 3: Add the password field type**

In `frontend/src/components/master-data/types.ts`, change:
```ts
export type FieldType = 'text' | 'number' | 'checkbox' | 'textarea' | 'select'
```
to:
```ts
export type FieldType = 'text' | 'number' | 'checkbox' | 'textarea' | 'select' | 'password'
```

In `frontend/src/components/master-data/EntityForm.vue`, change the first `<input>`'s condition and `type` binding from:
```vue
      <input
        v-if="field.type === 'text' || field.type === 'number'"
        :id="field.key"
        :type="field.type"
```
to:
```vue
      <input
        v-if="field.type === 'text' || field.type === 'number' || field.type === 'password'"
        :id="field.key"
        :type="field.type"
```

In `frontend/src/components/master-data/MasterDataView.vue`, the table shouldn't grow a "Password" column — a `password` field is write-only on the backend (the API never returns a value for it), so showing it would just be a permanently blank column. Change the `columns` computed from:
```ts
const columns = computed(() =>
  props.fields.filter((f) => f.type !== 'textarea').map((f) => ({ key: f.key, label: f.label })),
)
```
to:
```ts
const columns = computed(() =>
  props.fields
    .filter((f) => f.type !== 'textarea' && f.type !== 'password')
    .map((f) => ({ key: f.key, label: f.label })),
)
```

- [ ] **Step 4: Write the permission schema and Role UI**

Create `frontend/src/modules/roles/permissionSchema.ts`:

```ts
// Must match Role.MODULES / Role.ACTIONS in backend/apps/accounts/models.py exactly.
export const MODULES = ['operations', 'finance', 'sales', 'purchasing', 'admin'] as const
export const ACTIONS = ['view', 'create', 'edit', 'validate', 'cancel', 'export'] as const
```

Create `frontend/src/modules/roles/RoleFormModal.vue`:

```vue
<script setup lang="ts">
import { MODULES, ACTIONS } from './permissionSchema'

const props = defineProps<{
  modelValue: { name: string; permissions: Record<string, string[]> }
}>()
const emit = defineEmits<{
  'update:modelValue': [value: { name: string; permissions: Record<string, string[]> }]
  submit: []
  cancel: []
}>()

function isChecked(module: string, action: string) {
  return (props.modelValue.permissions[module] ?? []).includes(action)
}

function toggle(module: string, action: string) {
  const current = props.modelValue.permissions[module] ?? []
  const next = current.includes(action)
    ? current.filter((a) => a !== action)
    : [...current, action]
  emit('update:modelValue', {
    ...props.modelValue,
    permissions: { ...props.modelValue.permissions, [module]: next },
  })
}

function setName(value: string) {
  emit('update:modelValue', { ...props.modelValue, name: value })
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="$emit('submit')">
    <div class="space-y-1">
      <label class="text-sm font-medium text-slate-600" for="role-name">Name</label>
      <input
        id="role-name"
        :value="modelValue.name"
        required
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        @input="setName(($event.target as HTMLInputElement).value)"
      />
    </div>

    <table class="w-full text-left text-sm">
      <thead>
        <tr class="border-b text-slate-500">
          <th class="px-2 py-1 font-medium">Module</th>
          <th v-for="action in ACTIONS" :key="action" class="px-2 py-1 font-medium capitalize">
            {{ action }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="module in MODULES" :key="module" class="border-b last:border-0">
          <td class="px-2 py-1 capitalize">{{ module }}</td>
          <td v-for="action in ACTIONS" :key="action" class="px-2 py-1 text-center">
            <input
              type="checkbox"
              :checked="isChecked(module, action)"
              @change="toggle(module, action)"
            />
          </td>
        </tr>
      </tbody>
    </table>

    <div class="flex justify-end gap-2 pt-2">
      <button type="button" class="px-3 py-2 text-sm text-slate-500" @click="$emit('cancel')">
        Cancel
      </button>
      <button type="submit" class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white">
        Save
      </button>
    </div>
  </form>
</template>
```

Create `frontend/src/modules/roles/RoleListView.vue`:

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import RoleFormModal from './RoleFormModal.vue'
import { createResourceApi } from '@/api/resource'

interface RoleRecord {
  id: number
  name: string
  permissions: Record<string, string[]>
}

const resource = createResourceApi<RoleRecord>('/accounts/roles/')
const roles = ref<RoleRecord[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const formValue = ref<{ name: string; permissions: Record<string, string[]> }>({
  name: '',
  permissions: {},
})

async function load() {
  const data = await resource.list()
  roles.value = data.results
}

function openCreate() {
  editingId.value = null
  formValue.value = { name: '', permissions: {} }
  showForm.value = true
}

function openEdit(role: RoleRecord) {
  editingId.value = role.id
  formValue.value = { name: role.name, permissions: role.permissions }
  showForm.value = true
}

async function onSubmit() {
  if (editingId.value === null) {
    await resource.create(formValue.value)
  } else {
    await resource.update(editingId.value, formValue.value)
  }
  showForm.value = false
  await load()
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">Roles</h2>
      <button class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white" @click="openCreate">
        Add
      </button>
    </div>

    <ul class="divide-y rounded border bg-white">
      <li v-for="role in roles" :key="role.id" class="flex items-center justify-between px-3 py-2 text-sm">
        <span>{{ role.name }}</span>
        <button class="text-slate-500 hover:text-slate-800" @click="openEdit(role)">Edit</button>
      </li>
    </ul>

    <div v-if="showForm" class="fixed inset-0 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg">
        <h3 class="mb-4 text-base font-semibold text-slate-800">
          {{ editingId === null ? 'New' : 'Edit' }} Role
        </h3>
        <RoleFormModal v-model="formValue" @submit="onSubmit" @cancel="showForm = false" />
      </div>
    </div>
  </div>
</template>
```

Create `frontend/src/modules/users/UserView.vue`:

```vue
<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/accounts/users/')
const fields: FieldSchema[] = [
  { key: 'email', label: 'Email', type: 'text', required: true },
  { key: 'full_name', label: 'Full name', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'role', label: 'Role ID', type: 'number' },
  { key: 'password', label: 'Password', type: 'password' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Users" :resource="resource" :fields="fields" />
</template>
```

- [ ] **Step 5: Register the routes**

In `frontend/src/router/index.ts`, add two more entries to the `children` array (alongside `cash-accounts`):

```ts
        { path: 'users', name: 'users', component: () => import('@/modules/users/UserView.vue') },
        { path: 'roles', name: 'roles', component: () => import('@/modules/roles/RoleListView.vue') },
```

- [ ] **Step 6: Run tests, verify pass**

```bash
cd frontend
npx vitest run
```
Expected: all suites pass.

- [ ] **Step 7: Typecheck and build**

```bash
cd frontend
npx vue-tsc -b && npx vite build
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/master-data/ frontend/src/modules/roles/ frontend/src/modules/users/ frontend/src/modules/master-data/ frontend/src/router/
git commit -m "feat(frontend): add Users and Roles admin UI with permission-matrix editor"
```

---

## Task 11: Role-aware navigation

**Files:**
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/stores/__tests__/auth.spec.ts`
- Modify: `frontend/src/modules/shell/AppShell.vue`
- Create: `frontend/src/modules/shell/__tests__/AppShell.spec.ts`

**Interfaces:**
- Consumes: routes registered in Task 9/10 (`products`, `suppliers`, `customers`, `transporters`, `drivers`, `trucks`, `bank-accounts`, `cash-accounts`, `users`, `roles`).
- Produces: `useAuthStore().can(module: string, action: string): boolean` getter; `User.role_detail: {id, name, permissions} | null`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/stores/__tests__/auth.spec.ts` (inside the existing `describe('auth store', ...)` block):

```ts
  it('can() reflects the role permission matrix', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      email: 'ops@example.com',
      full_name: '',
      role: 3,
      role_detail: { id: 3, name: 'Operations', permissions: { operations: ['view', 'create'] } },
    }

    expect(auth.can('operations', 'create')).toBe(true)
    expect(auth.can('finance', 'view')).toBe(false)
  })

  it('can() returns false when there is no authenticated user', () => {
    const auth = useAuthStore()
    expect(auth.can('operations', 'view')).toBe(false)
  })
```

Create `frontend/src/modules/shell/__tests__/AppShell.spec.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '@/modules/shell/AppShell.vue'
import { useAuthStore } from '@/stores/auth'

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', component: stub },
      { path: '/products', name: 'products', component: stub },
      { path: '/suppliers', name: 'suppliers', component: stub },
      { path: '/users', name: 'users', component: stub },
      { path: '/roles', name: 'roles', component: stub },
    ],
  })
}

describe('AppShell navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('only shows nav items the user role can view', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 1,
      email: 'ops@example.com',
      full_name: 'Ops User',
      role: 3,
      role_detail: { id: 3, name: 'Operations', permissions: { operations: ['view'] } },
    }

    const wrapper = mount(AppShell, { global: { plugins: [router] } })

    expect(wrapper.text()).toContain('Products')
    expect(wrapper.text()).not.toContain('Users')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/stores src/modules/shell`
Expected: FAIL — `auth.can is not a function`, and `role_detail` doesn't exist on the `User` type (TS error surfaces as a vitest transform failure).

- [ ] **Step 3: Update the auth store**

Replace `frontend/src/stores/auth.ts`:

```ts
import { defineStore } from 'pinia'
import axios from 'axios'

interface RoleDetail {
  id: number
  name: string
  permissions: Record<string, string[]>
}

interface User {
  id: number
  email: string
  full_name: string
  role: number | null
  role_detail: RoleDetail | null
}

// Plain axios instance (not api/client.ts) so login/refresh never recurse
// through the 401-refresh interceptor.
const authHttp = axios.create({ baseURL: '/api' })

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem('access_token'),
    refreshToken: localStorage.getItem('refresh_token'),
    user: null as User | null,
  }),

  getters: {
    isAuthenticated: (state) => !!state.accessToken,
    can: (state) => (module: string, action: string) =>
      (state.user?.role_detail?.permissions[module] ?? []).includes(action),
  },

  actions: {
    async login(email: string, password: string) {
      const { data } = await authHttp.post('/auth/login/', { email, password })
      this.setTokens(data.access, data.refresh)
      await this.fetchMe()
    },

    async refresh(): Promise<boolean> {
      if (!this.refreshToken) return false
      try {
        const { data } = await authHttp.post('/auth/refresh/', {
          refresh: this.refreshToken,
        })
        this.setTokens(data.access, this.refreshToken)
        return true
      } catch {
        return false
      }
    },

    async fetchMe() {
      const { data } = await authHttp.get('/accounts/users/me/', {
        headers: { Authorization: `Bearer ${this.accessToken}` },
      })
      this.user = data
    },

    setTokens(access: string, refresh: string) {
      this.accessToken = access
      this.refreshToken = refresh
      localStorage.setItem('access_token', access)
      localStorage.setItem('refresh_token', refresh)
    },

    logout() {
      this.accessToken = null
      this.refreshToken = null
      this.user = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    },
  },
})
```

- [ ] **Step 4: Rewrite AppShell with role-aware navigation**

Replace `frontend/src/modules/shell/AppShell.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const NAV_ITEMS = [
  { to: 'products', label: 'Products', module: 'operations' },
  { to: 'suppliers', label: 'Suppliers', module: 'purchasing' },
  { to: 'customers', label: 'Customers', module: 'sales' },
  { to: 'transporters', label: 'Transporters', module: 'operations' },
  { to: 'drivers', label: 'Drivers', module: 'operations' },
  { to: 'trucks', label: 'Trucks', module: 'operations' },
  { to: 'bank-accounts', label: 'Bank Accounts', module: 'finance' },
  { to: 'cash-accounts', label: 'Cash Accounts', module: 'finance' },
  { to: 'users', label: 'Users', module: 'admin' },
  { to: 'roles', label: 'Roles', module: 'admin' },
] as const

const auth = useAuthStore()
const router = useRouter()

const visibleNavItems = computed(() => NAV_ITEMS.filter((item) => auth.can(item.module, 'view')))

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex min-h-screen bg-slate-50">
    <aside class="w-56 shrink-0 border-r bg-white">
      <div class="px-4 py-3 font-semibold text-slate-800">Fuel Logistics ERP</div>
      <nav class="flex flex-col gap-1 px-2">
        <RouterLink
          v-for="item in visibleNavItems"
          :key="item.to"
          :to="{ name: item.to }"
          class="rounded px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          active-class="bg-slate-100 font-medium text-slate-900"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <div class="flex-1">
      <header class="flex items-center justify-between border-b bg-white px-6 py-3 shadow-sm">
        <span class="text-sm text-slate-500">Fuel &amp; transport operations</span>
        <div class="flex items-center gap-4 text-sm text-slate-600">
          <span v-if="auth.user">
            {{ auth.user.full_name || auth.user.email }} · {{ auth.user.role_detail?.name }}
          </span>
          <button class="text-slate-500 hover:text-slate-800" @click="onLogout">Log out</button>
        </div>
      </header>
      <main class="p-6">
        <router-view />
      </main>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd frontend
npx vitest run
```
Expected: all suites pass.

- [ ] **Step 6: Typecheck and build**

```bash
cd frontend
npx vue-tsc -b && npx vite build
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/auth.ts frontend/src/stores/__tests__/ frontend/src/modules/shell/
git commit -m "feat(frontend): role-aware navigation driven by the permission matrix"
```

---

## Task 12: Full-stack verification

**Files:** none (verification only — no code changes expected).

**Interfaces:** none — this task exercises the system built by Tasks 1–11 end-to-end.

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend
pytest -v
```
Expected: every test across `accounts`, `core`, `suppliers`, `customers`, `transport`, `finance` passes.

- [ ] **Step 2: Run the full frontend test suite, typecheck, and build**

```bash
cd frontend
npx vitest run
npx vue-tsc -b
npx vite build
```
Expected: all green.

- [ ] **Step 3: Boot the full stack and exercise it through the browser-facing proxy**

```bash
cd /Users/mohamed/Downloads/fuel-logistics-erp
docker compose up -d --build
```

Wait for `backend` logs to show migrations applied, then create one Admin-role user and one Operations-role user:

```bash
docker compose exec backend python manage.py shell -c "
from apps.accounts.models import Role, User
admin_role = Role.objects.get(name=Role.NAME_ADMIN)
ops_role = Role.objects.get(name=Role.NAME_OPERATIONS)
User.objects.create_superuser(email='admin@example.com', password='testpass123', role=admin_role)
User.objects.create_user(email='ops@example.com', password='testpass123', role=ops_role)
"
```

- [ ] **Step 4: Verify the permission boundary through the live API**

```bash
OPS_TOKEN=$(curl -s -X POST http://localhost:5173/api/auth/login/ -H "Content-Type: application/json" \
  -d '{"email":"ops@example.com","password":"testpass123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access'])")

# Expect 201 — Operations role can create a Truck
curl -s -o /dev/null -w "Truck create: %{http_code}\n" -X POST http://localhost:5173/api/trucks/ \
  -H "Authorization: Bearer $OPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"internal_id":"TRK-VERIFY","tractor_registration":"AA-1-SN","tanker_registration":"BB-1-SN","capacity_litres":"45000.00","ownership_type":"COMPANY_OWNED"}'

# Expect 403 — Operations role cannot create a BankAccount
curl -s -o /dev/null -w "Bank account create: %{http_code}\n" -X POST http://localhost:5173/api/bank-accounts/ \
  -H "Authorization: Bearer $OPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Main Account","opening_balance":"1000000.00"}'
```
Expected: `Truck create: 201`, `Bank account create: 403`.

- [ ] **Step 5: Tear down**

```bash
docker compose down -v
```

- [ ] **Step 6: Commit (if any fixes were needed during verification)**

Only if Step 1–4 surfaced a bug that needed a fix outside the already-committed tasks:

```bash
git add -A
git commit -m "fix: address issue found during Phase 1 full-stack verification"
```
