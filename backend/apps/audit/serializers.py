from rest_framework import serializers

from apps.audit.labels import describe
from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    content_type_label = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    # UI recette fix (2026-09-05): Journal d'audit was showing the raw
    # (often synthetic/technical, e.g. "admin-empty@example.test") email in
    # the "Utilisateur" column - this app is phone/PIN-based, email is not
    # a user-facing identifier here. user_email is kept as-is (still the
    # literal email, in case another consumer needs it later) and this new
    # field is what the frontend now displays: full_name, else phone, else
    # email as a last resort.
    user_display_name = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "user_email",
            "user_display_name",
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

    def get_user_display_name(self, obj) -> str | None:
        if not obj.user_id:
            return None
        return obj.user.full_name or obj.user.phone or obj.user.email or None

    def get_summary(self, obj) -> dict:
        return describe(obj)
