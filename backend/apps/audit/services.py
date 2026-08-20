import datetime
from decimal import Decimal

from apps.audit.context import get_current_user
from apps.audit.models import AuditLog

CANCELLED_VALUE = "CANCELLED"


def _serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def build_snapshot(instance) -> dict:
    """Field-name -> JSON-safe value snapshot of every concrete, non-auto
    column on `instance` (docs/PHASE_6_PLAN.md Etape 1).

    Uses each field's `attname` (e.g. `customer_id` rather than `customer`)
    so a FK is captured as its raw id without ever re-fetching the related
    row, and skips the primary key plus any auto_now/auto_now_add column -
    those are storage metadata, not business state, and including
    `updated_at` here would make every save() look "changed" even when
    nothing business-relevant moved.
    """
    snapshot = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key:
            continue
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue
        snapshot[field.attname] = _serialize(getattr(instance, field.attname))
    return snapshot


class AuditLogService:
    """Writes AuditLog rows - the only code that constructs one directly
    (apps.audit.mixins.AuditableModel is the only caller in practice)."""

    @staticmethod
    def record(*, content_type, object_id, action, previous_value, new_value, user=None, reason=None):
        actor = user or get_current_user()
        return AuditLog.objects.create(
            user=actor,
            action=action,
            content_type=content_type,
            object_id=object_id,
            previous_value=previous_value,
            new_value=new_value,
            reason=reason,
        )

    @staticmethod
    def infer_update_action(previous_snapshot: dict, new_snapshot: dict) -> str:
        """UPDATE, unless this save just moved `status` to CANCELLED - that
        transition gets its own action so a cancellation is never
        indistinguishable from an ordinary field edit in the trail
        (ERP_Implementation_Experience_Guide.md Section 9.9;
        docs/PHASE_6_PLAN.md Etape 1)."""
        if (
            "status" in new_snapshot
            and new_snapshot.get("status") == CANCELLED_VALUE
            and previous_snapshot.get("status") != CANCELLED_VALUE
        ):
            return AuditLog.Action.CANCEL
        return AuditLog.Action.UPDATE
