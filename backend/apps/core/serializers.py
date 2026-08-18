from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import LossToleranceConfig, Product


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "code", "is_active", "created_at", "updated_at"]


class LossToleranceConfigSerializer(serializers.ModelSerializer):
    """docs/PHASE_4_PLAN.md Etape 6: GET|PATCH /api/settings/loss-tolerance/.

    updated_by_detail uses a SerializerMethodField rather than a nested
    UserSerializer(source="updated_by") - the "not yet configured" GET
    response represents an unsaved singleton instance whose updated_by_id is
    None, and touching the plain relation descriptor on that instance would
    raise RelatedObjectDoesNotExist (the FK itself has no null=True).
    """

    updated_by_detail = serializers.SerializerMethodField()

    class Meta:
        model = LossToleranceConfig
        fields = ["tolerance_litres", "updated_by", "updated_by_detail", "updated_at"]
        read_only_fields = ["updated_by", "updated_by_detail", "updated_at"]

    def get_updated_by_detail(self, obj) -> dict | None:
        if not obj.updated_by_id:
            return None
        return UserSerializer(obj.updated_by).data
