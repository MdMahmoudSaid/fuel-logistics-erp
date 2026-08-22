# Authentification Téléphone + PIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace email/password authentication with phone-number + 4-digit-PIN authentication, and introduce a reusable `CountryPhoneInput` component used across login and every master-data phone field.

**Architecture:** Backend: `User.phone` becomes `USERNAME_FIELD` (unique), `email` becomes optional/non-unique, the inherited `password` column is repurposed to store the hashed PIN, and a custom SimpleJWT serializer/view adds phone-based lookup plus a 5-attempt lockout. Frontend: a new `CountryPhoneInput.vue` (searchable country dropdown + digit-validated number field, backed by a static `countries.ts` list and `Intl.DisplayNames` for localized names) is wired into `EntityForm.vue` via a new `'phone'` `FieldType`, and into `LoginView.vue` directly; a new `'pin'` `FieldType` handles the 4-digit PIN everywhere it appears.

**Tech Stack:** Django 5.1 + DRF + djangorestframework-simplejwt 5.3.1 (backend), Vue 3 `<script setup>` + Pinia + vue-i18n 11 + Vitest/@vue/test-utils (frontend). No new dependencies on either side.

**Spec:** `docs/superpowers/specs/2026-08-22-phone-pin-auth-design.md`

## Global Constraints

- Normalized phone format everywhere (storage, API, frontend state): dial code + digits, no spaces, e.g. `+22212345678`.
- PIN is exactly 4 digits, enforced both client-side (native HTML `pattern`/`minlength`/`maxlength`) and server-side (`PinValidator`).
- Digit-count validation is exact for MR (8), ML (8), SN (9), NE (8); every other country uses a generic 6–14 digit range.
- Account lockout: 5 failed PIN attempts → 15-minute lock (`locked_until`), resets to 0/`null` on next success.
- No new npm/pip dependency. Country names are resolved via the browser-native `Intl.DisplayNames` API — no manual per-locale country-name translation.
- Pre-launch app, no real user data — clean migration, no data-migration step.
- Never add `Co-Authored-By: Claude` to commits (repo convention).

---

### Task 1: Backend — PIN validator

**Files:**
- Create: `backend/apps/accounts/validators.py`
- Modify: `backend/config/settings/base.py:87-92`
- Test: `backend/apps/accounts/tests.py` (append)

**Interfaces:**
- Produces: `apps.accounts.validators.PinValidator` — a Django password-validator class with `.validate(password, user=None)` and `.get_help_text()`, referenced by dotted path in `AUTH_PASSWORD_VALIDATORS`.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/accounts/tests.py`:

```python
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password


def test_pin_validator_accepts_four_digits():
    validate_password("1234")


@pytest.mark.parametrize("bad_pin", ["123", "12345", "abcd", "12a4", ""])
def test_pin_validator_rejects_invalid_pin(bad_pin):
    with pytest.raises(DjangoValidationError):
        validate_password(bad_pin)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k pin_validator -v`
Expected: FAIL (`test_pin_validator_accepts_four_digits` fails because the current validators reject an all-numeric password via `NumericPasswordValidator`, and `bad_pin=""`/short PINs currently fail for the wrong reason — `MinimumLengthValidator`, not our not-yet-existing `PinValidator`). Confirms the old validator set is still active.

- [ ] **Step 3: Create the validator**

`backend/apps/accounts/validators.py`:

```python
import re

from django.core.exceptions import ValidationError


class PinValidator:
    """Password validator repurposed for the 4-digit login PIN."""

    pin_re = re.compile(r"^\d{4}$")

    def validate(self, password, user=None):
        if not self.pin_re.match(password):
            raise ValidationError(
                "Le code PIN doit contenir exactement 4 chiffres.",
                code="pin_invalid",
            )

    def get_help_text(self):
        return "Le code PIN doit contenir exactement 4 chiffres."
```

- [ ] **Step 4: Wire it into settings**

In `backend/config/settings/base.py`, replace lines 87-92:

```python
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
```

with:

```python
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "apps.accounts.validators.PinValidator"},
]
```

(`NumericPasswordValidator` actively forbids all-numeric passwords, which is incompatible with a 4-digit PIN by definition — it must go, not just gain a sibling.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k pin_validator -v`
Expected: PASS (6 tests: 1 accept + 5 parametrized rejects)

- [ ] **Step 6: Commit**

```bash
git add backend/apps/accounts/validators.py backend/config/settings/base.py backend/apps/accounts/tests.py
git commit -m "feat(backend): add 4-digit PIN password validator"
```

---

### Task 2: Backend — `User` model & manager (phone auth)

**Files:**
- Modify: `backend/apps/accounts/models.py`
- Modify: `backend/apps/accounts/managers.py`
- Create: `backend/apps/accounts/migrations/0002_phone_pin_auth.py` (generated, not hand-written)
- Test: `backend/apps/accounts/tests.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `User.phone` (unique `CharField`, `USERNAME_FIELD`), `User.email` (optional, non-unique), `User.failed_pin_attempts: int`, `User.locked_until: datetime | None`, `User.is_locked() -> bool`, `UserManager.create_user(phone, pin=None, **extra_fields)`, `UserManager.create_superuser(phone, pin=None, **extra_fields)`. Later tasks (3, 4, 5) rely on these exact names.

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/accounts/tests.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k "not_locked_by_default or locked_when_locked_until" -v`
Expected: FAIL — `create_user()` currently requires `email`, not `phone`/`pin`, and `is_locked()` doesn't exist.

- [ ] **Step 3: Update the model**

Replace `backend/apps/accounts/models.py` lines 38-56 with:

```python
class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Custom user, phone-based login with PIN (§38)."""

    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    failed_pin_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    def __str__(self) -> str:
        return self.phone

    def is_locked(self) -> bool:
        from django.utils import timezone

        return bool(self.locked_until and self.locked_until > timezone.now())
```

- [ ] **Step 4: Update the manager**

Replace `backend/apps/accounts/managers.py` entirely with:

```python
from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone, pin, **extra_fields):
        if not phone:
            raise ValueError("Les utilisateurs doivent avoir un numéro de téléphone")
        user = self.model(phone=phone, **extra_fields)
        user.set_password(pin)
        user.save(using=self._db)
        return user

    def create_user(self, phone, pin=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, pin, **extra_fields)

    def create_superuser(self, phone, pin=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(phone, pin, **extra_fields)
```

- [ ] **Step 5: Generate and run the migration**

Run: `cd backend && .venv/bin/python manage.py makemigrations accounts`
Expected: creates `apps/accounts/migrations/0002_....py` altering `phone` (unique), `email` (non-unique, blank), adding `failed_pin_attempts`, `locked_until`. If Django prompts for a one-off default for the now-unique `phone` field (because existing rows exist in the dev DB), supply `+22200000000` as a throwaway placeholder — acceptable since this is pre-launch, no real data to preserve.

Run: `cd backend && .venv/bin/python manage.py migrate`
Expected: migration applies cleanly.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k "not_locked_by_default or locked_when_locked_until" -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/apps/accounts/models.py backend/apps/accounts/managers.py backend/apps/accounts/migrations/ backend/apps/accounts/tests.py
git commit -m "feat(backend): make phone the auth identifier, PIN replaces password"
```

---

### Task 3: Backend — phone+PIN login endpoint with lockout

**Files:**
- Create: `backend/apps/accounts/auth.py`
- Modify: `backend/config/urls.py:6,10`
- Test: `backend/apps/accounts/tests.py` (append)

**Interfaces:**
- Consumes: `User.is_locked()`, `User.failed_pin_attempts`, `User.locked_until` (Task 2).
- Produces: `apps.accounts.auth.PhonePinTokenObtainPairView` — DRF view mounted at `/api/auth/login/`, request body `{"phone": str, "pin": str}`, response `{"access": str, "refresh": str}` on success, HTTP 401 on invalid credentials or lockout.

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/accounts/tests.py`:

```python
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
```

(`APIClient` is already imported mid-file at this point in `tests.py`; if not yet in scope for these lines, add `from rest_framework.test import APIClient` at the top of the appended block.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k "login_with_phone_and_pin or login_with_wrong_pin" -v`
Expected: FAIL — `/api/auth/login/` still expects `{email, password}` via the default `TokenObtainPairView`, so posting `{phone, pin}` returns 400 (missing required fields).

- [ ] **Step 3: Create the custom serializer and view**

`backend/apps/accounts/auth.py`:

```python
from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User

MAX_FAILED_PIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class PhonePinTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pin"] = self.fields.pop("password")

    def validate(self, attrs):
        phone = attrs.get(self.username_field)
        pin = attrs.get("pin")

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise AuthenticationFailed("Numéro de téléphone ou code PIN invalide.")

        if user.is_locked():
            raise AuthenticationFailed("Compte verrouillé. Réessayez dans quelques minutes.")

        if not user.is_active or not user.check_password(pin):
            user.failed_pin_attempts += 1
            if user.failed_pin_attempts >= MAX_FAILED_PIN_ATTEMPTS:
                user.locked_until = timezone.now() + LOCKOUT_DURATION
            user.save(update_fields=["failed_pin_attempts", "locked_until"])
            raise AuthenticationFailed("Numéro de téléphone ou code PIN invalide.")

        if user.failed_pin_attempts or user.locked_until:
            user.failed_pin_attempts = 0
            user.locked_until = None
            user.save(update_fields=["failed_pin_attempts", "locked_until"])

        refresh = self.get_token(user)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}


class PhonePinTokenObtainPairView(TokenObtainPairView):
    serializer_class = PhonePinTokenObtainPairSerializer
```

`TokenObtainSerializer.__init__` (SimpleJWT internals) always sets `self.fields[self.username_field] = CharField()` and `self.fields["password"] = PasswordField()`; our `__init__` renames the second field to `pin` so the public API is `{phone, pin}` end to end, matching the frontend contract.

- [ ] **Step 4: Wire the view into urls**

In `backend/config/urls.py`, replace line 6:

```python
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
```

with:

```python
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.auth import PhonePinTokenObtainPairView
```

and replace line 10:

```python
    path("api/auth/login/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
```

with:

```python
    path("api/auth/login/", PhonePinTokenObtainPairView.as_view(), name="token_obtain_pair"),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k "login_with_phone_and_pin or login_with_wrong_pin" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/apps/accounts/auth.py backend/config/urls.py backend/apps/accounts/tests.py
git commit -m "feat(backend): phone+PIN login endpoint"
```

---

### Task 4: Backend — `UserSerializer` PIN field & admin

**Files:**
- Modify: `backend/apps/accounts/serializers.py`
- Modify: `backend/apps/accounts/admin.py`
- Test: `backend/apps/accounts/tests.py` (append)

**Interfaces:**
- Consumes: `User` model fields from Task 2.
- Produces: `UserSerializer` exposes `pin` (write-only) instead of `password`; `fields` list includes `phone`/`email` instead of the old `email`-only identifier.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/accounts/tests.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k invalid_pin -v`
Expected: FAIL — `UserSerializer` has no `pin` field yet, so the request body's `pin` key is ignored and the write succeeds (or fails for an unrelated reason).

- [ ] **Step 3: Update the serializer**

Replace `backend/apps/accounts/serializers.py`'s `UserSerializer` class with:

```python
class UserSerializer(serializers.ModelSerializer):
    pin = serializers.CharField(write_only=True, required=False, min_length=4, max_length=4)
    role_detail = RoleSerializer(source="role", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "email",
            "full_name",
            "role",
            "role_detail",
            "is_active",
            "pin",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_pin(self, value):
        try:
            validate_password(value, self.instance)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def create(self, validated_data):
        pin = validated_data.pop("pin", None)
        user = User(**validated_data)
        if pin:
            user.set_password(pin)
        user.save()
        return user

    def update(self, instance, validated_data):
        pin = validated_data.pop("pin", None)
        user = super().update(instance, validated_data)
        if pin:
            user.set_password(pin)
            user.save()
        return user
```

- [ ] **Step 4: Update the admin**

Replace `backend/apps/accounts/admin.py`'s `UserAdmin` class body with:

```python
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["phone"]
    list_display = ["phone", "email", "full_name", "role", "is_active", "is_staff"]
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Personal info", {"fields": ("full_name", "email", "role")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "password1", "password2", "role"),
            },
        ),
    )
    search_fields = ["phone", "email", "full_name"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -k invalid_pin -v`
Expected: PASS (4 parametrized cases)

- [ ] **Step 6: Commit**

```bash
git add backend/apps/accounts/serializers.py backend/apps/accounts/admin.py backend/apps/accounts/tests.py
git commit -m "feat(backend): expose PIN on UserSerializer, update admin for phone auth"
```

---

### Task 5: Backend — fix pre-existing tests broken by the phone/PIN migration

**Files:**
- Modify: `backend/apps/accounts/tests.py` (full rewrite)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: nothing new — this task's deliverable is "the whole `accounts` test module passes."

**Context:** Tasks 1-4 only appended new tests. The tests that existed before this plan (`test_user_role_optional_at_db_level`, `test_me_endpoint_includes_role_detail`, `test_non_admin_cannot_list_users`, `test_admin_can_create_user_and_role_endpoints_work`, `test_admin_cannot_create_user_with_weak_password`, `test_login_with_valid_and_invalid_credentials`, `test_token_refresh_issues_new_access_token`) still call `User.objects.create_user(email=..., password=...)` and POST `{email, password}` — all broken now. This task fixes them and folds in the two new lockout tests from the spec.

- [ ] **Step 1: Confirm the current failures**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/tests.py -v`
Expected: FAIL on the pre-existing tests listed above (they raise `TypeError: create_user() missing 1 required positional argument: 'phone'` or similar) while the new tests from Tasks 1-4 pass.

- [ ] **Step 2: Replace the full file**

Replace the entire contents of `backend/apps/accounts/tests.py` with:

```python
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
```

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest apps/accounts/ -v`
Expected: PASS, all tests green.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/accounts/tests.py
git commit -m "test(backend): convert accounts tests to phone+PIN, add lockout coverage"
```

---

### Task 6: Frontend — `countries.ts` data

**Files:**
- Create: `frontend/src/data/countries.ts`
- Test: `frontend/src/data/__tests__/countries.spec.ts`

**Interfaces:**
- Produces: `COUNTRIES: {iso2: string; dialCode: string}[]`, `PRIORITY_ISO2: string[]`, `PHONE_DIGIT_RULES: Record<string, {min: number; max: number}>`, `DEFAULT_DIGIT_RULE: {min: number; max: number}`, `DEFAULT_ISO2: string`. Consumed by `CountryPhoneInput.vue` (Task 7).

- [ ] **Step 1: Write the failing test**

`frontend/src/data/__tests__/countries.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  COUNTRIES,
  PRIORITY_ISO2,
  PHONE_DIGIT_RULES,
  DEFAULT_DIGIT_RULE,
  DEFAULT_ISO2,
} from '@/data/countries'

describe('countries data', () => {
  it('includes the four priority Sahel countries with exact digit rules', () => {
    expect(PRIORITY_ISO2).toEqual(['MR', 'ML', 'SN', 'NE'])
    expect(PHONE_DIGIT_RULES.MR).toEqual({ min: 8, max: 8 })
    expect(PHONE_DIGIT_RULES.ML).toEqual({ min: 8, max: 8 })
    expect(PHONE_DIGIT_RULES.SN).toEqual({ min: 9, max: 9 })
    expect(PHONE_DIGIT_RULES.NE).toEqual({ min: 8, max: 8 })
  })

  it('has a unique entry per ISO2 code and covers every priority country', () => {
    const codes = COUNTRIES.map((c) => c.iso2)
    expect(new Set(codes).size).toBe(codes.length)
    for (const iso2 of PRIORITY_ISO2) {
      expect(codes).toContain(iso2)
    }
  })

  it('falls back to the default digit rule and default country for unlisted codes', () => {
    expect(PHONE_DIGIT_RULES.XX).toBeUndefined()
    expect(DEFAULT_DIGIT_RULE).toEqual({ min: 6, max: 14 })
    expect(COUNTRIES.some((c) => c.iso2 === DEFAULT_ISO2)).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:unit -- countries.spec.ts`
Expected: FAIL — `@/data/countries` doesn't exist yet.

- [ ] **Step 3: Create the data file**

`frontend/src/data/countries.ts`:

```ts
// ISO 3166-1 alpha-2 + E.164 calling codes. Sovereign states only (no
// dependent territories) — extend this list as new operating countries
// are added. Country display names are resolved at render time via
// Intl.DisplayNames (see CountryPhoneInput.vue), not stored here.

export interface Country {
  iso2: string
  dialCode: string
}

export const DEFAULT_ISO2 = 'MR'

export const PRIORITY_ISO2 = ['MR', 'ML', 'SN', 'NE']

export const PHONE_DIGIT_RULES: Record<string, { min: number; max: number }> = {
  MR: { min: 8, max: 8 },
  ML: { min: 8, max: 8 },
  SN: { min: 9, max: 9 },
  NE: { min: 8, max: 8 },
}

export const DEFAULT_DIGIT_RULE = { min: 6, max: 14 }

export const COUNTRIES: Country[] = [
  // Africa
  { iso2: 'DZ', dialCode: '+213' },
  { iso2: 'AO', dialCode: '+244' },
  { iso2: 'BJ', dialCode: '+229' },
  { iso2: 'BW', dialCode: '+267' },
  { iso2: 'BF', dialCode: '+226' },
  { iso2: 'BI', dialCode: '+257' },
  { iso2: 'CV', dialCode: '+238' },
  { iso2: 'CM', dialCode: '+237' },
  { iso2: 'CF', dialCode: '+236' },
  { iso2: 'TD', dialCode: '+235' },
  { iso2: 'KM', dialCode: '+269' },
  { iso2: 'CG', dialCode: '+242' },
  { iso2: 'CD', dialCode: '+243' },
  { iso2: 'CI', dialCode: '+225' },
  { iso2: 'DJ', dialCode: '+253' },
  { iso2: 'EG', dialCode: '+20' },
  { iso2: 'GQ', dialCode: '+240' },
  { iso2: 'ER', dialCode: '+291' },
  { iso2: 'SZ', dialCode: '+268' },
  { iso2: 'ET', dialCode: '+251' },
  { iso2: 'GA', dialCode: '+241' },
  { iso2: 'GM', dialCode: '+220' },
  { iso2: 'GH', dialCode: '+233' },
  { iso2: 'GN', dialCode: '+224' },
  { iso2: 'GW', dialCode: '+245' },
  { iso2: 'KE', dialCode: '+254' },
  { iso2: 'LS', dialCode: '+266' },
  { iso2: 'LR', dialCode: '+231' },
  { iso2: 'LY', dialCode: '+218' },
  { iso2: 'MG', dialCode: '+261' },
  { iso2: 'MW', dialCode: '+265' },
  { iso2: 'ML', dialCode: '+223' },
  { iso2: 'MR', dialCode: '+222' },
  { iso2: 'MU', dialCode: '+230' },
  { iso2: 'MA', dialCode: '+212' },
  { iso2: 'MZ', dialCode: '+258' },
  { iso2: 'NA', dialCode: '+264' },
  { iso2: 'NE', dialCode: '+227' },
  { iso2: 'NG', dialCode: '+234' },
  { iso2: 'RW', dialCode: '+250' },
  { iso2: 'ST', dialCode: '+239' },
  { iso2: 'SN', dialCode: '+221' },
  { iso2: 'SC', dialCode: '+248' },
  { iso2: 'SL', dialCode: '+232' },
  { iso2: 'SO', dialCode: '+252' },
  { iso2: 'ZA', dialCode: '+27' },
  { iso2: 'SS', dialCode: '+211' },
  { iso2: 'SD', dialCode: '+249' },
  { iso2: 'TZ', dialCode: '+255' },
  { iso2: 'TG', dialCode: '+228' },
  { iso2: 'TN', dialCode: '+216' },
  { iso2: 'UG', dialCode: '+256' },
  { iso2: 'ZM', dialCode: '+260' },
  { iso2: 'ZW', dialCode: '+263' },
  // Americas
  { iso2: 'AR', dialCode: '+54' },
  { iso2: 'BS', dialCode: '+1' },
  { iso2: 'BB', dialCode: '+1' },
  { iso2: 'BZ', dialCode: '+501' },
  { iso2: 'BO', dialCode: '+591' },
  { iso2: 'BR', dialCode: '+55' },
  { iso2: 'CA', dialCode: '+1' },
  { iso2: 'CL', dialCode: '+56' },
  { iso2: 'CO', dialCode: '+57' },
  { iso2: 'CR', dialCode: '+506' },
  { iso2: 'CU', dialCode: '+53' },
  { iso2: 'DM', dialCode: '+1' },
  { iso2: 'DO', dialCode: '+1' },
  { iso2: 'EC', dialCode: '+593' },
  { iso2: 'SV', dialCode: '+503' },
  { iso2: 'GD', dialCode: '+1' },
  { iso2: 'GT', dialCode: '+502' },
  { iso2: 'GY', dialCode: '+592' },
  { iso2: 'HT', dialCode: '+509' },
  { iso2: 'HN', dialCode: '+504' },
  { iso2: 'JM', dialCode: '+1' },
  { iso2: 'MX', dialCode: '+52' },
  { iso2: 'NI', dialCode: '+505' },
  { iso2: 'PA', dialCode: '+507' },
  { iso2: 'PY', dialCode: '+595' },
  { iso2: 'PE', dialCode: '+51' },
  { iso2: 'KN', dialCode: '+1' },
  { iso2: 'LC', dialCode: '+1' },
  { iso2: 'VC', dialCode: '+1' },
  { iso2: 'SR', dialCode: '+597' },
  { iso2: 'TT', dialCode: '+1' },
  { iso2: 'US', dialCode: '+1' },
  { iso2: 'UY', dialCode: '+598' },
  { iso2: 'VE', dialCode: '+58' },
  // Asia
  { iso2: 'AF', dialCode: '+93' },
  { iso2: 'AM', dialCode: '+374' },
  { iso2: 'AZ', dialCode: '+994' },
  { iso2: 'BH', dialCode: '+973' },
  { iso2: 'BD', dialCode: '+880' },
  { iso2: 'BT', dialCode: '+975' },
  { iso2: 'BN', dialCode: '+673' },
  { iso2: 'KH', dialCode: '+855' },
  { iso2: 'CN', dialCode: '+86' },
  { iso2: 'CY', dialCode: '+357' },
  { iso2: 'GE', dialCode: '+995' },
  { iso2: 'IN', dialCode: '+91' },
  { iso2: 'ID', dialCode: '+62' },
  { iso2: 'IR', dialCode: '+98' },
  { iso2: 'IQ', dialCode: '+964' },
  { iso2: 'IL', dialCode: '+972' },
  { iso2: 'JP', dialCode: '+81' },
  { iso2: 'JO', dialCode: '+962' },
  { iso2: 'KZ', dialCode: '+7' },
  { iso2: 'KW', dialCode: '+965' },
  { iso2: 'KG', dialCode: '+996' },
  { iso2: 'LA', dialCode: '+856' },
  { iso2: 'LB', dialCode: '+961' },
  { iso2: 'MY', dialCode: '+60' },
  { iso2: 'MV', dialCode: '+960' },
  { iso2: 'MN', dialCode: '+976' },
  { iso2: 'MM', dialCode: '+95' },
  { iso2: 'NP', dialCode: '+977' },
  { iso2: 'KP', dialCode: '+850' },
  { iso2: 'OM', dialCode: '+968' },
  { iso2: 'PK', dialCode: '+92' },
  { iso2: 'PS', dialCode: '+970' },
  { iso2: 'PH', dialCode: '+63' },
  { iso2: 'QA', dialCode: '+974' },
  { iso2: 'SA', dialCode: '+966' },
  { iso2: 'SG', dialCode: '+65' },
  { iso2: 'KR', dialCode: '+82' },
  { iso2: 'LK', dialCode: '+94' },
  { iso2: 'SY', dialCode: '+963' },
  { iso2: 'TW', dialCode: '+886' },
  { iso2: 'TJ', dialCode: '+992' },
  { iso2: 'TH', dialCode: '+66' },
  { iso2: 'TL', dialCode: '+670' },
  { iso2: 'TR', dialCode: '+90' },
  { iso2: 'TM', dialCode: '+993' },
  { iso2: 'AE', dialCode: '+971' },
  { iso2: 'UZ', dialCode: '+998' },
  { iso2: 'VN', dialCode: '+84' },
  { iso2: 'YE', dialCode: '+967' },
  // Europe
  { iso2: 'AL', dialCode: '+355' },
  { iso2: 'AD', dialCode: '+376' },
  { iso2: 'AT', dialCode: '+43' },
  { iso2: 'BY', dialCode: '+375' },
  { iso2: 'BE', dialCode: '+32' },
  { iso2: 'BA', dialCode: '+387' },
  { iso2: 'BG', dialCode: '+359' },
  { iso2: 'HR', dialCode: '+385' },
  { iso2: 'CZ', dialCode: '+420' },
  { iso2: 'DK', dialCode: '+45' },
  { iso2: 'EE', dialCode: '+372' },
  { iso2: 'FI', dialCode: '+358' },
  { iso2: 'FR', dialCode: '+33' },
  { iso2: 'DE', dialCode: '+49' },
  { iso2: 'GR', dialCode: '+30' },
  { iso2: 'HU', dialCode: '+36' },
  { iso2: 'IS', dialCode: '+354' },
  { iso2: 'IE', dialCode: '+353' },
  { iso2: 'IT', dialCode: '+39' },
  { iso2: 'LV', dialCode: '+371' },
  { iso2: 'LI', dialCode: '+423' },
  { iso2: 'LT', dialCode: '+370' },
  { iso2: 'LU', dialCode: '+352' },
  { iso2: 'MT', dialCode: '+356' },
  { iso2: 'MD', dialCode: '+373' },
  { iso2: 'MC', dialCode: '+377' },
  { iso2: 'ME', dialCode: '+382' },
  { iso2: 'NL', dialCode: '+31' },
  { iso2: 'MK', dialCode: '+389' },
  { iso2: 'NO', dialCode: '+47' },
  { iso2: 'PL', dialCode: '+48' },
  { iso2: 'PT', dialCode: '+351' },
  { iso2: 'RO', dialCode: '+40' },
  { iso2: 'RU', dialCode: '+7' },
  { iso2: 'SM', dialCode: '+378' },
  { iso2: 'RS', dialCode: '+381' },
  { iso2: 'SK', dialCode: '+421' },
  { iso2: 'SI', dialCode: '+386' },
  { iso2: 'ES', dialCode: '+34' },
  { iso2: 'SE', dialCode: '+46' },
  { iso2: 'CH', dialCode: '+41' },
  { iso2: 'UA', dialCode: '+380' },
  { iso2: 'GB', dialCode: '+44' },
  { iso2: 'VA', dialCode: '+379' },
  // Oceania
  { iso2: 'AU', dialCode: '+61' },
  { iso2: 'FJ', dialCode: '+679' },
  { iso2: 'KI', dialCode: '+686' },
  { iso2: 'MH', dialCode: '+692' },
  { iso2: 'FM', dialCode: '+691' },
  { iso2: 'NR', dialCode: '+674' },
  { iso2: 'NZ', dialCode: '+64' },
  { iso2: 'PW', dialCode: '+680' },
  { iso2: 'PG', dialCode: '+675' },
  { iso2: 'WS', dialCode: '+685' },
  { iso2: 'SB', dialCode: '+677' },
  { iso2: 'TO', dialCode: '+676' },
  { iso2: 'TV', dialCode: '+688' },
  { iso2: 'VU', dialCode: '+678' },
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:unit -- countries.spec.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/data/countries.ts frontend/src/data/__tests__/countries.spec.ts
git commit -m "feat(frontend): add country dial-code data with Sahel priority list"
```

---

### Task 7: Frontend — `CountryPhoneInput.vue`

**Files:**
- Create: `frontend/src/components/ui/CountryPhoneInput.vue`
- Test: `frontend/src/components/ui/__tests__/CountryPhoneInput.spec.ts`

**Interfaces:**
- Consumes: `COUNTRIES`, `PRIORITY_ISO2`, `PHONE_DIGIT_RULES`, `DEFAULT_DIGIT_RULE`, `DEFAULT_ISO2` from `@/data/countries` (Task 6).
- Produces: `CountryPhoneInput` component — props `{ id: string; modelValue: string; label?: string; required?: boolean; disabled?: boolean; error?: string }`, emits `update:modelValue: [value: string]`. `modelValue` is the normalized `dialCode + digits` string. Consumed by `EntityForm.vue` (Task 8) and `LoginView.vue` (Task 10).

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/ui/__tests__/CountryPhoneInput.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CountryPhoneInput from '@/components/ui/CountryPhoneInput.vue'
import { i18n } from '@/i18n'

describe('CountryPhoneInput', () => {
  it('defaults to Mauritania and emits the normalized number as digits are typed', async () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '' },
      global: { plugins: [i18n] },
    })

    await wrapper.find('input#phone').setValue('12345678')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['+22212345678'])
  })

  it('parses an existing normalized value back into country + national number', () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '+22112345678' },
      global: { plugins: [i18n] },
    })

    expect((wrapper.find('input#phone').element as HTMLInputElement).value).toBe('12345678')
  })

  it('filters the country dropdown by typed name', async () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '' },
      global: { plugins: [i18n] },
    })

    const dropdown = wrapper.findAll('input')[0]
    await dropdown.trigger('focus')
    await dropdown.setValue('Mauri')

    expect(wrapper.text()).toContain('+222')
  })

  it('enforces the Senegal 9-digit rule via the maxlength attribute', async () => {
    const wrapper = mount(CountryPhoneInput, {
      props: { id: 'phone', modelValue: '+221123456789' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('input#phone').attributes('maxlength')).toBe('9')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:unit -- CountryPhoneInput.spec.ts`
Expected: FAIL — component doesn't exist yet.

- [ ] **Step 3: Create the component**

`frontend/src/components/ui/CountryPhoneInput.vue`:

```vue
<script setup lang="ts">
defineOptions({ name: 'UiCountryPhoneInput' })

import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  COUNTRIES,
  PRIORITY_ISO2,
  PHONE_DIGIT_RULES,
  DEFAULT_DIGIT_RULE,
  DEFAULT_ISO2,
} from '@/data/countries'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: string
    label?: string
    required?: boolean
    disabled?: boolean
    error?: string
  }>(),
  { label: undefined, required: false, disabled: false, error: undefined },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const { t, locale } = useI18n()

function parsePhone(value: string): { iso2: string; national: string } {
  if (!value) return { iso2: DEFAULT_ISO2, national: '' }
  const match = [...COUNTRIES]
    .filter((c) => value.startsWith(c.dialCode))
    .sort((a, b) => b.dialCode.length - a.dialCode.length)[0]
  if (!match) return { iso2: DEFAULT_ISO2, national: value.replace(/\D/g, '') }
  return { iso2: match.iso2, national: value.slice(match.dialCode.length) }
}

const selectedIso2 = ref(DEFAULT_ISO2)
const nationalNumber = ref('')
const query = ref('')
const open = ref(false)
const numberInput = ref<HTMLInputElement | null>(null)

watch(
  () => props.modelValue,
  (value) => {
    const parsed = parsePhone(value)
    selectedIso2.value = parsed.iso2
    nationalNumber.value = parsed.national
  },
  { immediate: true },
)

const selectedCountry = computed(
  () => COUNTRIES.find((c) => c.iso2 === selectedIso2.value) ?? COUNTRIES[0],
)

const digitRule = computed(() => PHONE_DIGIT_RULES[selectedIso2.value] ?? DEFAULT_DIGIT_RULE)

function countryName(iso2: string): string {
  try {
    return new Intl.DisplayNames([locale.value], { type: 'region' }).of(iso2) ?? iso2
  } catch {
    return iso2
  }
}

const orderedCountries = computed(() => {
  const priority = PRIORITY_ISO2.map((iso2) => COUNTRIES.find((c) => c.iso2 === iso2)).filter(
    (c): c is (typeof COUNTRIES)[number] => Boolean(c),
  )
  const rest = COUNTRIES.filter((c) => !PRIORITY_ISO2.includes(c.iso2)).sort((a, b) =>
    countryName(a.iso2).localeCompare(countryName(b.iso2), locale.value),
  )
  return [...priority, ...rest]
})

const filteredCountries = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return orderedCountries.value
  return orderedCountries.value.filter(
    (c) =>
      countryName(c.iso2).toLowerCase().includes(q) ||
      c.dialCode.includes(q) ||
      c.iso2.toLowerCase().includes(q),
  )
})

function emitValue() {
  emit(
    'update:modelValue',
    nationalNumber.value ? selectedCountry.value.dialCode + nationalNumber.value : '',
  )
}

function onNumberInput(event: Event) {
  const digits = (event.target as HTMLInputElement).value
    .replace(/\D/g, '')
    .slice(0, digitRule.value.max)
  nationalNumber.value = digits
  emitValue()
}

function selectCountry(iso2: string) {
  selectedIso2.value = iso2
  const rule = PHONE_DIGIT_RULES[iso2] ?? DEFAULT_DIGIT_RULE
  nationalNumber.value = nationalNumber.value.slice(0, rule.max)
  open.value = false
  query.value = ''
  emitValue()
  numberInput.value?.focus()
}

function onDropdownFocus() {
  open.value = true
  query.value = ''
}

function onDropdownBlur() {
  open.value = false
  query.value = ''
}
</script>

<template>
  <div class="space-y-1.5">
    <label v-if="label" :for="id" class="text-texte-2 text-sm font-medium">{{ label }}</label>
    <div class="flex gap-2">
      <div class="relative w-36 shrink-0">
        <input
          type="text"
          :value="open ? query : `${countryName(selectedIso2)} (${selectedCountry.dialCode})`"
          class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-2.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          :placeholder="t('common.search')"
          :disabled="disabled"
          @focus="onDropdownFocus"
          @blur="onDropdownBlur"
          @input="query = ($event.target as HTMLInputElement).value"
          @keydown.escape="($event.target as HTMLInputElement).blur()"
        />
        <ul
          v-if="open"
          class="border-ligne absolute z-20 mt-1 max-h-56 w-56 overflow-auto rounded-lg border bg-white text-sm shadow-lg"
        >
          <li
            v-for="country in filteredCountries"
            :key="country.iso2"
            class="hover:bg-sable cursor-pointer px-3 py-2"
            @mousedown.prevent="selectCountry(country.iso2)"
          >
            {{ countryName(country.iso2) }} ({{ country.dialCode }})
          </li>
          <li v-if="filteredCountries.length === 0" class="text-texte-3 px-3 py-2">
            {{ t('common.noResults') }}
          </li>
        </ul>
      </div>
      <input
        :id="id"
        ref="numberInput"
        type="text"
        inputmode="numeric"
        :value="nationalNumber"
        :required="required"
        :disabled="disabled"
        :minlength="digitRule.min"
        :maxlength="digitRule.max"
        :pattern="`\\d{${digitRule.min},${digitRule.max}}`"
        :aria-invalid="!!error"
        class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        :class="error ? 'border-critique' : ''"
        @input="onNumberInput"
      />
    </div>
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
  </div>
</template>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:unit -- CountryPhoneInput.spec.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/CountryPhoneInput.vue frontend/src/components/ui/__tests__/CountryPhoneInput.spec.ts
git commit -m "feat(frontend): add CountryPhoneInput component"
```

---

### Task 8: Frontend — wire `'phone'`/`'pin'` field types into the master-data form system

**Files:**
- Modify: `frontend/src/components/master-data/types.ts`
- Modify: `frontend/src/components/master-data/EntityForm.vue`
- Modify: `frontend/src/components/master-data/MasterDataView.vue:27`
- Test: `frontend/src/components/master-data/__tests__/EntityForm.spec.ts` (append)

**Interfaces:**
- Consumes: `CountryPhoneInput` (Task 7).
- Produces: `FieldType` now includes `'phone' | 'pin'`. Consumed by `UserView.vue`, `CustomerView.vue`, `SupplierView.vue`, `TransporterView.vue`, `DriverView.vue` (Task 9).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/master-data/__tests__/EntityForm.spec.ts`:

```ts
it('renders a phone field with the CountryPhoneInput component', () => {
  const fields: FieldSchema[] = [{ key: 'phone', label: 'Phone', type: 'phone' }]
  const wrapper = mount(EntityForm, {
    props: { fields, modelValue: {} },
    global: { plugins: [i18n] },
  })

  expect(wrapper.find('input#phone').exists()).toBe(true)
})

it('renders a pin field as a 4-digit numeric input', () => {
  const fields: FieldSchema[] = [{ key: 'pin', label: 'PIN', type: 'pin' }]
  const wrapper = mount(EntityForm, {
    props: { fields, modelValue: {} },
    global: { plugins: [i18n] },
  })

  const input = wrapper.find('input#pin')
  expect(input.attributes('inputmode')).toBe('numeric')
  expect(input.attributes('maxlength')).toBe('4')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:unit -- EntityForm.spec.ts`
Expected: FAIL — `'phone'`/`'pin'` aren't valid `FieldType`s and `EntityForm` has no branch for them (TypeScript will also flag the test file itself once `FieldType` doesn't include these — expected at this point).

- [ ] **Step 3: Extend `FieldType`**

`frontend/src/components/master-data/types.ts` line 1:

```ts
export type FieldType =
  | 'text'
  | 'number'
  | 'checkbox'
  | 'textarea'
  | 'select'
  | 'password'
  | 'phone'
  | 'pin'
```

- [ ] **Step 4: Add branches to `EntityForm.vue`**

Add the import at the top of `frontend/src/components/master-data/EntityForm.vue` (after the existing `Button` import):

```ts
import CountryPhoneInput from '@/components/ui/CountryPhoneInput.vue'
```

Insert two new branches right after the existing text/number/password `<input>` (before the `<textarea>` branch):

```html
<CountryPhoneInput
  v-else-if="field.type === 'phone'"
  :id="field.key"
  :model-value="(modelValue[field.key] as string) ?? ''"
  :required="field.required"
  @update:model-value="setField(field.key, $event)"
/>

<input
  v-else-if="field.type === 'pin'"
  :id="field.key"
  type="text"
  inputmode="numeric"
  pattern="\d{4}"
  minlength="4"
  maxlength="4"
  :required="field.required"
  :value="modelValue[field.key] as string | undefined"
  class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
  @input="setField(field.key, ($event.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, 4))"
/>
```

- [ ] **Step 5: Exclude `'pin'` from the table columns**

`frontend/src/components/master-data/MasterDataView.vue` line 27, change:

```ts
    .filter((f) => f.type !== 'textarea' && f.type !== 'password')
```

to:

```ts
    .filter((f) => f.type !== 'textarea' && f.type !== 'password' && f.type !== 'pin')
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm run test:unit -- EntityForm.spec.ts`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/master-data/types.ts frontend/src/components/master-data/EntityForm.vue frontend/src/components/master-data/MasterDataView.vue frontend/src/components/master-data/__tests__/EntityForm.spec.ts
git commit -m "feat(frontend): add phone and pin field types to the generic form system"
```

---

### Task 9: Frontend — apply the new field types across master-data views

**Files:**
- Modify: `frontend/src/modules/customers/CustomerView.vue:14`
- Modify: `frontend/src/modules/suppliers/SupplierView.vue:15`
- Modify: `frontend/src/modules/transporters/TransporterView.vue:14`
- Modify: `frontend/src/modules/drivers/DriverView.vue:13`
- Modify: `frontend/src/modules/users/UserView.vue:18-30`
- Modify: `frontend/src/locales/fr.json`, `frontend/src/locales/en.json`, `frontend/src/locales/ar.json` (`masterData.fields.pin`)

**Interfaces:**
- Consumes: `'phone'`/`'pin'` `FieldType` (Task 8).
- Produces: nothing new — this task's deliverable is "master data forms render the new widgets," verified via the existing `masterDataViews.spec.ts` (already passes without changes since it only checks title/non-empty schema) plus a manual check in Step 3.

- [ ] **Step 1: Swap the four one-line phone fields**

In each of these files, change the `phone` field's `type: 'text'` to `type: 'phone'`:

`frontend/src/modules/customers/CustomerView.vue:14`:
```ts
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
```

`frontend/src/modules/suppliers/SupplierView.vue:15`:
```ts
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
```

`frontend/src/modules/transporters/TransporterView.vue:14`:
```ts
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
```

`frontend/src/modules/drivers/DriverView.vue:13`:
```ts
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
```

- [ ] **Step 2: Update `UserView.vue`'s field schema**

Replace `frontend/src/modules/users/UserView.vue` lines 18-30:

```ts
const fields = computed<FieldSchema[]>(() => [
  { key: 'email', label: t('masterData.fields.email'), type: 'text', required: true },
  { key: 'full_name', label: t('masterData.fields.fullName'), type: 'text' },
  { key: 'phone', label: t('masterData.fields.phone'), type: 'text' },
  {
    key: 'role',
    label: t('masterData.fields.roleId'),
    type: 'select',
    options: roles.value.map((r) => ({ value: String(r.id), label: r.name })),
  },
  { key: 'password', label: t('masterData.fields.password'), type: 'password' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
```

with:

```ts
const fields = computed<FieldSchema[]>(() => [
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone', required: true },
  { key: 'full_name', label: t('masterData.fields.fullName'), type: 'text' },
  { key: 'email', label: t('masterData.fields.email'), type: 'text' },
  {
    key: 'role',
    label: t('masterData.fields.roleId'),
    type: 'select',
    options: roles.value.map((r) => ({ value: String(r.id), label: r.name })),
  },
  { key: 'pin', label: t('masterData.fields.pin'), type: 'pin' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
```

- [ ] **Step 3: Add the `masterData.fields.pin` translation key**

In `frontend/src/locales/fr.json`, inside the `masterData.fields` object, add (next to `"password": "Mot de passe"`):
```json
"pin": "Code PIN",
```

In `frontend/src/locales/en.json`, same location:
```json
"pin": "PIN code",
```

In `frontend/src/locales/ar.json`, same location:
```json
"pin": "رمز PIN",
```

- [ ] **Step 4: Run the existing regression test**

Run: `cd frontend && npm run test:unit -- masterDataViews.spec.ts EntityForm.spec.ts MasterDataView.spec.ts`
Expected: PASS — these were already generic enough not to break, this step confirms it.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/customers/CustomerView.vue frontend/src/modules/suppliers/SupplierView.vue frontend/src/modules/transporters/TransporterView.vue frontend/src/modules/drivers/DriverView.vue frontend/src/modules/users/UserView.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json
git commit -m "feat(frontend): use CountryPhoneInput and PIN field across master data forms"
```

---

### Task 10: Frontend — `LoginView.vue` + auth store

**Files:**
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/modules/auth/LoginView.vue`
- Modify: `frontend/src/locales/fr.json`, `frontend/src/locales/en.json`, `frontend/src/locales/ar.json` (`auth.*`)
- Modify: `frontend/src/modules/auth/__tests__/LoginView.spec.ts`
- Modify: `frontend/src/stores/__tests__/auth.spec.ts`

**Interfaces:**
- Consumes: `CountryPhoneInput` (Task 7).
- Produces: `useAuthStore().login(phone: string, pin: string): Promise<void>`, POST body `{phone, pin}`. `User` interface: `{id, phone, email, full_name, role, role_detail}`.

- [ ] **Step 1: Write the failing tests**

Replace `frontend/src/modules/auth/__tests__/LoginView.spec.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '@/modules/auth/LoginView.vue'
import { i18n } from '@/i18n'

describe('LoginView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the sign-in form', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: LoginView },
      ],
    })
    router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: { plugins: [router, i18n] },
    })

    expect(wrapper.find('input#phone').exists()).toBe(true)
    expect(wrapper.find('input#pin').exists()).toBe(true)
    expect(wrapper.find('button[type="submit"]').text()).toContain('Se connecter')
  })
})
```

Replace the `can() reflects the role permission matrix` test's user object in `frontend/src/stores/__tests__/auth.spec.ts`:

```ts
  it('can() reflects the role permission matrix', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22112345678',
      email: '',
      full_name: '',
      role: 3,
      role_detail: { id: 3, name: 'Operations', permissions: { operations: ['view', 'create'] } },
    }

    expect(auth.can('operations', 'create')).toBe(true)
    expect(auth.can('finance', 'view')).toBe(false)
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:unit -- LoginView.spec.ts auth.spec.ts`
Expected: FAIL — `input#phone`/`input#pin` don't exist yet (still `input#email`/`input#password`); the `User` type mismatch also surfaces as a TS error.

- [ ] **Step 3: Update the auth store**

Replace `frontend/src/stores/auth.ts` lines 10-16 and 36-40:

```ts
interface User {
  id: number
  phone: string
  email: string
  full_name: string
  role: number | null
  role_detail: RoleDetail | null
}
```

```ts
    async login(phone: string, pin: string) {
      const { data } = await authHttp.post('/auth/login/', { phone, pin })
      this.setTokens(data.access, data.refresh)
      await this.fetchMe()
    },
```

- [ ] **Step 4: Update `LoginView.vue`**

Replace `frontend/src/modules/auth/LoginView.vue` entirely with:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLogo from '@/components/AppLogo.vue'
import CountryPhoneInput from '@/components/ui/CountryPhoneInput.vue'
import Button from '@/components/ui/Button.vue'

const { t } = useI18n()

const phone = ref('')
const pin = ref('')
const error = ref('')
const loading = ref(false)
const showPin = ref(false)

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

function onPinInput(event: Event) {
  pin.value = (event.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, 4)
}

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(phone.value, pin.value)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch {
    error.value = t('auth.invalidCredentials')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="bg-sable flex min-h-screen">
    <!-- Panneau de marque (desktop) -->
    <div
      class="bg-bitume relative hidden w-1/2 flex-col justify-between overflow-hidden p-10 lg:flex"
    >
      <AppLogo tone="light" :size="32" />
      <div class="relative z-10">
        <p class="font-display text-sable max-w-sm text-3xl leading-tight font-semibold uppercase">
          {{ t('auth.tagline') }}
        </p>
      </div>
      <svg
        class="pointer-events-none absolute -right-24 -bottom-24 opacity-[0.08]"
        width="420"
        height="420"
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M9 21a7 7 0 1 1 14 0"
          stroke="#F97316"
          stroke-width="1.4"
          stroke-dasharray="1 2.2"
        />
        <line x1="16" y1="21" x2="20.2" y2="16.4" stroke="#F97316" stroke-width="1.4" />
      </svg>
    </div>

    <!-- Formulaire -->
    <div class="flex flex-1 flex-col items-center justify-center p-6">
      <div class="w-full max-w-sm">
        <div class="mb-8 flex justify-center lg:hidden">
          <AppLogo :size="32" />
        </div>

        <form
          class="bg-surface border-ligne space-y-5 rounded-xl border p-7 shadow-sm"
          @submit.prevent="onSubmit"
        >
          <div>
            <h1 class="font-display text-texte text-2xl font-semibold uppercase">
              {{ t('auth.title') }}
            </h1>
            <p class="text-texte-2 mt-1 text-sm">{{ t('auth.subtitle') }}</p>
          </div>

          <CountryPhoneInput id="phone" v-model="phone" :label="t('auth.phoneLabel')" required />

          <div class="space-y-1.5">
            <label for="pin" class="text-texte-2 text-sm font-medium">
              {{ t('auth.pinLabel') }}
            </label>
            <div class="relative">
              <input
                id="pin"
                :value="pin"
                :type="showPin ? 'text' : 'password'"
                inputmode="numeric"
                pattern="\d{4}"
                minlength="4"
                maxlength="4"
                autocomplete="current-password"
                required
                class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 pr-11 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                @input="onPinInput"
              />
              <div class="absolute inset-y-0 right-1.5 flex items-center">
                <button
                  type="button"
                  class="text-texte-3 hover:text-texte-2 flex h-8 w-8 items-center justify-center rounded-md transition"
                  :aria-label="showPin ? t('auth.hidePassword') : t('auth.showPassword')"
                  @click="showPin = !showPin"
                >
                  <svg
                    v-if="showPin"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.4 5.5A9.9 9.9 0 0 1 12 5.2c4.2 0 7.8 2.6 9.5 6.3a10.5 10.5 0 0 1-2.9 3.7M6.5 6.9A10.6 10.6 0 0 0 2.5 11.5c1.7 3.7 5.3 6.3 9.5 6.3a9.6 9.6 0 0 0 3.4-.6"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M2.5 11.5C4.2 7.8 7.8 5.2 12 5.2s7.8 2.6 9.5 6.3c-1.7 3.7-5.3 6.3-9.5 6.3s-7.8-2.6-9.5-6.3Z"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                    <circle cx="12" cy="11.5" r="2.6" stroke="currentColor" stroke-width="1.8" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <p v-if="error" class="text-critique text-sm" role="alert">{{ error }}</p>

          <Button type="submit" variant="primary" size="md" :disabled="loading" class="w-full">
            {{ loading ? t('auth.signingIn') : t('auth.signIn') }}
          </Button>
        </form>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Update the i18n `auth` keys**

In `frontend/src/locales/fr.json`, replace the `auth` object's `emailLabel`/`passwordLabel`/`invalidCredentials` and add `accountLocked`:

```json
"phoneLabel": "Téléphone",
"pinLabel": "Code PIN",
"invalidCredentials": "Numéro de téléphone ou code PIN invalide.",
"accountLocked": "Compte verrouillé. Réessayez dans quelques minutes.",
"showPassword": "Afficher le code PIN",
"hidePassword": "Masquer le code PIN"
```

In `frontend/src/locales/en.json`:

```json
"phoneLabel": "Phone number",
"pinLabel": "PIN code",
"invalidCredentials": "Invalid phone number or PIN.",
"accountLocked": "Account locked. Try again in a few minutes.",
"showPassword": "Show PIN",
"hidePassword": "Hide PIN"
```

In `frontend/src/locales/ar.json`:

```json
"phoneLabel": "رقم الهاتف",
"pinLabel": "رمز PIN",
"invalidCredentials": "رقم الهاتف أو رمز PIN غير صحيح.",
"accountLocked": "الحساب مقفل. حاول مرة أخرى بعد بضع دقائق.",
"showPassword": "إظهار رمز PIN",
"hidePassword": "إخفاء رمز PIN"
```

(Keep `tagline`, `title`, `subtitle`, `signIn`, `signingIn` unchanged in all three files; remove `emailLabel`/`passwordLabel` since nothing references them anymore.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm run test:unit -- LoginView.spec.ts auth.spec.ts`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/auth.ts frontend/src/modules/auth/LoginView.vue frontend/src/locales/fr.json frontend/src/locales/en.json frontend/src/locales/ar.json frontend/src/modules/auth/__tests__/LoginView.spec.ts frontend/src/stores/__tests__/auth.spec.ts
git commit -m "feat(frontend): phone+PIN login form and auth store"
```

---

### Task 11: Final verification & docs cleanup

**Files:**
- Modify: `LANCER_LOCALEMENT.md:143`

**Interfaces:**
- Consumes: everything from Tasks 1-10.
- Produces: nothing new — full-stack green build/test confirmation.

- [ ] **Step 1: Update the stale local-dev note**

`LANCER_LOCALEMENT.md` line 143 currently reads:

```
- Un compte de test créé pendant la recette Phase 6 existe encore en base (si tu n'as pas fait `down -v`) : `recette-phase6@test.local` / `Recette123!` (rôle Admin).
```

Replace it with:

```
- Le compte de test créé pendant la recette Phase 6 (`recette-phase6@test.local` / `Recette123!`) ne fonctionne plus : l'authentification est passée à téléphone + PIN. Crée un nouveau compte via `python manage.py createsuperuser` (il te demandera un téléphone et un PIN à 4 chiffres) ou via l'écran Utilisateurs une fois connecté avec un compte existant.
```

- [ ] **Step 2: Run the full backend test suite**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, no failures anywhere in the suite (not just `apps/accounts/`).

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && npm run test:unit`
Expected: PASS, no failures.

- [ ] **Step 4: Run the frontend build**

Run: `cd frontend && npm run build`
Expected: succeeds — this also runs `vue-tsc -b`, which will catch any leftover type mismatches (e.g. a stale reference to `User.email` as required, or a missing `FieldType` case) across the whole app, not just the files touched directly.

- [ ] **Step 5: Fix any regressions surfaced by steps 2-4**

If the backend suite, frontend suite, or build surfaces a failure outside the files this plan touched (e.g. another component destructuring `auth.user.email` as non-optional), fix it in place — re-run the relevant command until green before proceeding. Do not skip or silence a failure.

- [ ] **Step 6: Commit**

```bash
git add LANCER_LOCALEMENT.md
git commit -m "docs: update local-dev test account note for phone+PIN auth"
```

---

## Self-Review Notes

- **Spec coverage:** §1 model → Task 2; §2 validation/lockout → Tasks 1, 3; §3 serializer/admin/migration/tests → Tasks 2, 4, 5, 11; §4 CountryPhoneInput → Tasks 6, 7; §5 integration → Tasks 8, 9, 10; §6 i18n → Tasks 9, 10; §7 tests → distributed throughout + Task 11. No gaps found.
- **Placeholder scan:** no TBD/TODO markers; every step has literal code or an exact command.
- **Type consistency:** `User.phone`/`User.email`/`User.pin` (backend) and `phone`/`pin` (frontend store, `CountryPhoneInput` props, `FieldType`) are spelled identically everywhere they're introduced and consumed. `PhonePinTokenObtainPairView` (Task 3) is the exact name imported in `config/urls.py`. `CountryPhoneInput`'s emit name (`update:modelValue`) matches its usage as `@update:model-value` in `EntityForm.vue` and as `v-model` in `LoginView.vue`.
