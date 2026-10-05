from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.audit.exceptions import HardDeleteBlocked
from apps.audit.models import AuditLog
from apps.audit.services import AuditLogService, build_snapshot


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

    def save(self, *args, user=None, reason=None, **kwargs):
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
