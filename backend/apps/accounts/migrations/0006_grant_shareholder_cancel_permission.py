# Reverses "Task 7 ruling 2" (see 0005_seed_shareholder_permissions.py and
# ShareholderProfitDistribution's docstring): after the 2026-09-08 recette
# bug where the same real profit was distributed three times with no way
# to undo any of them, the shareholders module gained a cancel workflow
# (ShareholderDistributionService.cancel_distribution). Admin and
# Management get the "cancel" tier back; Finance stays view/create only,
# unchanged.

from django.db import migrations

ROLES_GAINING_CANCEL = ["Admin", "Management"]


def grant_shareholder_cancel(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in ROLES_GAINING_CANCEL:
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        actions = list(role.permissions.get("shareholders", []))
        if "cancel" not in actions:
            actions.append("cancel")
        role.permissions = {**role.permissions, "shareholders": actions}
        role.save(update_fields=["permissions"])


def revoke_shareholder_cancel(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name in ROLES_GAINING_CANCEL:
        try:
            role = Role.objects.get(name=name)
        except Role.DoesNotExist:
            continue
        actions = [a for a in role.permissions.get("shareholders", []) if a != "cancel"]
        role.permissions = {**role.permissions, "shareholders": actions}
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_seed_shareholder_permissions"),
        ("finance", "0020_shareholderprofitdistribution_cancellation"),
    ]
    operations = [migrations.RunPython(grant_shareholder_cancel, revoke_shareholder_cancel)]
