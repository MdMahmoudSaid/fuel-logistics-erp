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
