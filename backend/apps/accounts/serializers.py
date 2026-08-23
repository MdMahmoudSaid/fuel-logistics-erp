from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Role, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "permissions", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_permissions(self, value):
        for module, actions in value.items():
            if module not in Role.MODULES:
                raise serializers.ValidationError(f"Module inconnu : {module}")
            unknown_actions = set(actions) - set(Role.ACTIONS)
            if unknown_actions:
                raise serializers.ValidationError(f"Actions inconnues : {unknown_actions}")
        return value


class UserSerializer(serializers.ModelSerializer):
    pin = serializers.CharField(write_only=True, required=False, min_length=4, max_length=4)
    role_detail = RoleSerializer(source="role", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "email",
            "full_name",
            "role",
            "role_detail",
            "is_active",
            "pin",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_pin(self, value):
        try:
            validate_password(value, self.instance)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def create(self, validated_data):
        pin = validated_data.pop("pin", None)
        user = User(**validated_data)
        if pin:
            user.set_password(pin)
        user.save()
        return user

    def update(self, instance, validated_data):
        pin = validated_data.pop("pin", None)
        user = super().update(instance, validated_data)
        if pin:
            user.set_password(pin)
            user.save()
        return user
