from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


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
