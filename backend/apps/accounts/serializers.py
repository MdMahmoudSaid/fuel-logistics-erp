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
                raise serializers.ValidationError(f"Unknown module: {module}")
            unknown_actions = set(actions) - set(Role.ACTIONS)
            if unknown_actions:
                raise serializers.ValidationError(f"Unknown actions: {unknown_actions}")
        return value


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    role_detail = RoleSerializer(source="role", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "role_detail",
            "is_active",
            "password",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user
