from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.core.models import TimeStampedModel

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Custom user, email-based login (§38).

    `role` is a placeholder CharField for the scaffold. Phase 1 replaces it
    with a `Role` FK carrying the per-module View/Create/Edit/Validate/Cancel/
    Export permission matrix described in roadmap/phase_1_foundation.md.
    """

    class RoleChoices(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        MANAGEMENT = "MANAGEMENT", "Management"
        OPERATIONS = "OPERATIONS", "Operations"
        FINANCE = "FINANCE", "Finance"

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(
        max_length=20, choices=RoleChoices.choices, default=RoleChoices.OPERATIONS
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self) -> str:
        return self.email
