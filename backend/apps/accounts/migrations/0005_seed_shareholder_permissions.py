# Grants the new "shareholders" module (Task 7, client modifications plan)
# to the roles seeded in 0002_seed_roles, following the same
# RunPython-forward/reverse pattern as 0003_seed_reports_module_permissions.
#
# Admin and Management get view/create/edit/validate/export - deliberately
# NOT "cancel" (Task 7 ruling 2: this module has no cancellation workflow,
# see ShareholderProfitDistribution/ShareholderLoan docstrings). Finance
# gets view/create only. Operations gets nothing on this module.

from django.db import migrations

SHAREHOLDER_PERMISSIONS = {
    "Admin": ["view", "create", "edit", "validate", "export"],
    "Management": ["view", "create", "edit", "validate", "export"],
    "Finance": ["view", "create"],
}


def seed_shareholder_permissions(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name, actions in SHAREHOLDER_PERMISSIONS.items():
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        role.permissions = {**role.permissions, "shareholders": actions}
        role.save(update_fields=["permissions"])


def unseed_shareholder_permissions(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in SHAREHOLDER_PERMISSIONS:
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        role.permissions.pop("shareholders", None)
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_user_failed_pin_attempts_user_locked_until_and_more")]
    operations = [migrations.RunPython(seed_shareholder_permissions, unseed_shareholder_permissions)]
