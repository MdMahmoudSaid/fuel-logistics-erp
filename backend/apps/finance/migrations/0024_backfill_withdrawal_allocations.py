from django.db import migrations


def backfill_allocations(apps, schema_editor):
    ShareholderWithdrawal = apps.get_model("finance", "ShareholderWithdrawal")
    ShareholderWithdrawalAllocation = apps.get_model("finance", "ShareholderWithdrawalAllocation")

    for withdrawal in ShareholderWithdrawal.objects.filter(profit_share__isnull=False):
        ShareholderWithdrawalAllocation.objects.create(
            withdrawal=withdrawal,
            profit_share_id=withdrawal.profit_share_id,
            amount=withdrawal.amount,
        )


def reverse_backfill(apps, schema_editor):
    ShareholderWithdrawalAllocation = apps.get_model("finance", "ShareholderWithdrawalAllocation")
    ShareholderWithdrawalAllocation.objects.filter(profit_share__isnull=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0023_shareholderwithdrawalallocation"),
    ]

    operations = [
        migrations.RunPython(backfill_allocations, reverse_backfill),
    ]
