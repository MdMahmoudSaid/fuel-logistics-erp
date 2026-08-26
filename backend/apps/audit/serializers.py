from rest_framework import serializers

from apps.audit.labels import describe
from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    content_type_label = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "user_email",
            "timestamp",
            "action",
            "content_type",
            "content_type_label",
            "object_id",
            "previous_value",
            "new_value",
            "reason",
            "summary",
        ]
        read_only_fields = fields

    def get_content_type_label(self, obj) -> str:
        return f"{obj.content_type.app_label}.{obj.content_type.model}"

    def get_user_email(self, obj) -> str | None:
        return obj.user.email if obj.user_id else None

    def get_summary(self, obj) -> dict:
        return describe(obj)
