from django.db import transaction
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import (
    CompanyBankAccount,
    CompanyProfile,
    LossToleranceConfig,
    Product,
    split_contact_values,
)


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


class CompanyBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyBankAccount
        fields = ["id", "bank", "swift", "account_number", "is_active"]
        read_only_fields = ["id"]


class CompanyProfileSerializer(serializers.ModelSerializer):
    """bank_accounts is replaced as a whole when sent, kept when omitted."""

    bank_accounts = CompanyBankAccountSerializer(many=True, required=False)

    class Meta:
        model = CompanyProfile
        fields = [
            "name", "tagline", "tax_id", "trade_register", "address", "city",
            "phone", "email", "website", "bank_accounts",
        ]

    MAX_CONTACT_VALUES = 10

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Older single-field spellings ("a / b") come back as one value per line.
        data["phone"] = "\n".join(split_contact_values(data["phone"], phones=True))
        data["email"] = "\n".join(split_contact_values(data["email"]))
        return data

    def _normalise(self, value, *, phones):
        values = split_contact_values(value, phones=phones)
        if len(values) > self.MAX_CONTACT_VALUES:
            raise serializers.ValidationError(f"{self.MAX_CONTACT_VALUES} valeurs au maximum.")
        return "\n".join(values)

    def validate_phone(self, value):
        return self._normalise(value, phones=True)

    def validate_email(self, value):
        return self._normalise(value, phones=False)

    @transaction.atomic
    def update(self, instance, validated_data):
        banks = validated_data.pop("bank_accounts", None)
        instance = super().update(instance, validated_data)
        if banks is not None:
            instance.bank_accounts.all().delete()
            for position, bank in enumerate(banks):
                CompanyBankAccount.objects.create(profile=instance, position=position, **bank)
        return instance
