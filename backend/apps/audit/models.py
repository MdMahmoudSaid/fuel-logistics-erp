from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class AuditLog(models.Model):
    """Immutable trail of every mutation on an audited model
    (docs/PHASE_6_PLAN.md Etape 1; ERP_Implementation_Experience_Guide.md
    Section 9.9; Spec Section 39).

    Rows are only ever written by apps.audit.services.AuditLogService, from
    AuditableModel.save()/delete() - never constructed by hand elsewhere -
    so previous_value/new_value can always be trusted to be the real
    before/after state of the row, not a caller's guess (same immutability
    contract as trips.TripStatusHistory).

    `user` is nullable: capture is automatic (via the request-scoped
    current user, see apps.audit.context), and there is no such user for
    changes made outside an HTTP request (scripts, management commands,
    direct ORM/test usage) - those are legitimately attributed to no one
    rather than raising or inventing an actor.
    """

    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        CANCEL = "CANCEL", "Cancel"
        REVERSE = "REVERSE", "Reverse"

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=10, choices=Action.choices)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="audit_logs"
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    previous_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField()
    reason = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.content_type}#{self.object_id} @ {self.timestamp}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("AuditLog records are immutable and cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog records are immutable and cannot be deleted.")
