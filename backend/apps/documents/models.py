# Generic Document model (§35) attachable to any entity via GenericForeignKey.
# Implemented alongside the Phase 1 entities that first need attachments —
# see roadmap/phase_1_foundation.md.

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class Document(TimeStampedModel):
    """A physical file (PDF, scan, image) attached to any domain object.

    Option B from docs/PHASE_2_PLAN.md §1.C: a single generic-relation table
    rather than one nullable FK per owning model, so new attachable entities
    (Phase 3+ trips, deliveries, payments...) need no schema change here.
    """

    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    document_type = models.CharField(max_length=50)  # e.g. 'purchase_contract', 'cession_pdf'
    reference = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="uploaded_documents"
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return self.reference or f"{self.document_type} #{self.pk}"
