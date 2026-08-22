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

    MODULES = ["operations", "finance", "sales", "purchasing", "admin", "reports"]
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
