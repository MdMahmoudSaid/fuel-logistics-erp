# Grants the new "reports" module (Dashboard/Reports/Search - Role.MODULES,
# docs/PHASE_6_PLAN.md Etape 5) to the roles seeded in 0002_seed_roles, at
# the same relative tier each already has on the other modules: Admin gets
# every action, Management/Finance get view+export (they already have that
# pair everywhere else), Operations gets view only.

from django.db import migrations

REPORTS_PERMISSIONS = {
    "Admin": ["view", "create", "edit", "validate", "cancel", "export"],
    "Management": ["view", "export"],
    "Operations": ["view"],
    "Finance": ["view", "export"],
}


def seed_reports_permissions(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name, actions in REPORTS_PERMISSIONS.items():
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        role.permissions = {**role.permissions, "reports": actions}
        role.save(update_fields=["permissions"])


def unseed_reports_permissions(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in REPORTS_PERMISSIONS:
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        role.permissions.pop("reports", None)
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_seed_roles")]
    operations = [migrations.RunPython(seed_reports_permissions, unseed_reports_permissions)]
