# 2026-09-08 corrective review, point 6: a DB-level guarantee that two
# non-cancelled ShareholderProfitDistribution rows can never cover
# overlapping periods. The service-level .exists() check is not atomic
# against two concurrent creates - this exclusion constraint is.
#
# btree_gist is enabled defensively (a range && already has a GiST opclass
# in core, but the extension is the documented companion for
# ExclusionConstraint and lets a later constraint mix in a scalar term).

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
from django.conf import settings
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0020_shareholderprofitdistribution_cancellation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        BtreeGistExtension(),
        migrations.AddConstraint(
            model_name="shareholderprofitdistribution",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("status__in", ["DRAFT", "VALIDATED"])),
                expressions=[
                    (
                        models.Func(
                            models.F("period_start"),
                            models.F("period_end"),
                            models.Value("[]"),
                            function="daterange",
                            output_field=django.contrib.postgres.fields.ranges.DateRangeField(),
                        ),
                        "&&",
                    )
                ],
                name="finance_shrdist_no_overlapping_active_period",
            ),
        ),
    ]
