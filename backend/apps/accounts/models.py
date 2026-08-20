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
