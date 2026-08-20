# AuditLogViewSet (docs/PHASE_6_PLAN.md Etape 5): read-only history browser
# for administrators, filterable by object (content_type + object_id).

from rest_framework import viewsets

from apps.accounts.permissions import HasModulePermission
from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("content_type", "user").all()
    serializer_class = AuditLogSerializer
    filterset_fields = ["content_type", "object_id", "action"]
    permission_classes = [HasModulePermission]
    module = "admin"
