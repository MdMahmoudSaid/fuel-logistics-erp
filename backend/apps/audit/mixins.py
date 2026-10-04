from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.apps import apps
from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.audit.exceptions import HardDeleteBlocked
from apps.audit.models import AuditLog
from apps.audit.services import AuditLogService, build_snapshot

_profit_period_table_ready = None

# Only records that can change the profit calculation are period-locked.
# Cash movements such as a shareholder withdrawing an already-distributed
# share must remain possible after closure, even when paid on the closing
# date itself.
_PROFIT_AFFECTING_MODELS = {
    "finance.expense",
    "finance.expenseallocation",
    "finance.transportpayment",
    "purchasing.supplierorder",
    "sales.invoice",
    "sales.invoicecorrection",
    "sales.sale",
    "trips.clientverificationcorrection",
    "trips.deliverycontrol",
}


def assert_profit_period_dates_unlocked(dates) -> None:
    """Reject writes associated with dates covered by a closed period."""
    global _profit_period_table_ready
    if _profit_period_table_ready is None:
        _profit_period_table_ready = (
            "finance_shareholderprofitperiod" in connection.introspection.table_names()
        )
    if not _profit_period_table_ready:
        return
    Period = apps.get_model("finance", "ShareholderProfitPeriod")
    locked = next((
        period
        for event_date in dates
        if event_date is not None
        and (period := Period.objects.filter(
            status="CLOSED", start_date__lte=event_date, end_date__gte=event_date
        ).first())
    ), None)
    if locked:
        raise ValidationError({
            "detail": (
                f"La periode {locked.start_date} - {locked.end_date} est cloturee. "
                "Rouvrez-la avec un motif avant de modifier ses operations."
            )
        })


class AuditableModel(models.Model):
    """Abstract base that automatically writes an AuditLog entry on every
    create/update and blocks physical deletion once a record has moved
    past draft (docs/PHASE_6_PLAN.md Etape 1;
    ERP_Implementation_Experience_Guide.md Section 9.3/9.9).

    No caller needs to change: `Model.objects.create(...)` and plain
    `instance.save()` keep working exactly as before, and the actor is
    picked up automatically from the request-scoped current user (see
    apps.audit.context) unless the caller passes `save(user=..., reason=...)`
    explicitly.

    Subclasses that have a genuine draft state must override
    `is_locked_for_deletion()`; everything else defaults to "never
    hard-deletable" (guide Section 1.C: cancellation, not deletion, is the
    only path once a financial record is validated).
    """

    class Meta:
        abstract = True

    def is_locked_for_deletion(self) -> bool:
        return True

    def _assert_profit_period_unlocked(self) -> None:
        """Reject dated financial writes inside a CLOSED profit period.

        Imports are resolved through Django's app registry so the audit app
        remains independent from finance at module-import time.
        """
        if self._meta.label_lower not in _PROFIT_AFFECTING_MODELS:
            return
        dates = []
        for field_name in (
            "date", "payment_date", "purchase_date", "control_date", "issued_date"
        ):
            value = getattr(self, field_name, None)
            if value is not None:
                dates.append(value)
        if getattr(self, "trip_id", None):
            dates.append(self.trip.loading_date)
        if getattr(self, "sale_id", None):
            dates.append(self.sale.trip.loading_date)
        if self._meta.label_lower == "purchasing.supplierorder" and self.pk:
            dates.extend(self.trips.values_list("loading_date", flat=True))
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None:
                for field_name in (
                    "date", "payment_date", "purchase_date", "control_date", "issued_date"
                ):
                    value = getattr(previous, field_name, None)
                    if value is not None:
                        dates.append(value)
                if getattr(previous, "trip_id", None):
                    dates.append(previous.trip.loading_date)
                if getattr(previous, "sale_id", None):
                    dates.append(previous.sale.trip.loading_date)
        assert_profit_period_dates_unlocked(dates)

    def save(
        self, *args, user=None, reason=None, _skip_profit_period_lock=False, **kwargs
    ):
        # Private escape hatch used only after a model-specific method has
        # proved that a write cannot alter profit.  Callers must not expose
        # this flag through serializers or generic model APIs.
        if not _skip_profit_period_lock:
            self._assert_profit_period_unlocked()
        is_create = self.pk is None
        previous_snapshot = None
        if not is_create:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None:
                previous_snapshot = build_snapshot(previous)

        super().save(*args, **kwargs)

        content_type = ContentType.objects.get_for_model(type(self))
        new_snapshot = build_snapshot(self)

        if is_create:
            AuditLogService.record(
                content_type=content_type,
                object_id=self.pk,
                action=AuditLog.Action.CREATE,
                previous_value=None,
                new_value=new_snapshot,
                user=user,
                reason=reason,
            )
        elif previous_snapshot is not None and previous_snapshot != new_snapshot:
            AuditLogService.record(
                content_type=content_type,
                object_id=self.pk,
                action=AuditLogService.infer_update_action(previous_snapshot, new_snapshot),
                previous_value=previous_snapshot,
                new_value=new_snapshot,
                user=user,
                reason=reason,
            )

    def delete(self, *args, user=None, reason=None, **kwargs):
        self._assert_profit_period_unlocked()
        if self.is_locked_for_deletion():
            raise HardDeleteBlocked(
                f"{type(self).__name__} #{self.pk} cannot be physically "
                "deleted once past draft; cancel it instead."
            )
        content_type = ContentType.objects.get_for_model(type(self))
        object_id = self.pk
        previous_snapshot = build_snapshot(self)

        result = super().delete(*args, **kwargs)

        AuditLogService.record(
            content_type=content_type,
            object_id=object_id,
            action=AuditLog.Action.DELETE,
            previous_value=previous_snapshot,
            new_value={"deleted": True},
            user=user,
            reason=reason,
        )
        return result
