from rest_framework import serializers

from .models import Driver, Transporter, Truck


class TransporterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transporter
        fields = [
            "id", "name", "company_name", "phone", "address",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DriverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = [
            "id", "name", "phone", "license_number", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class TruckSerializer(serializers.ModelSerializer):
    class Meta:
        model = Truck
        fields = [
            "id", "internal_id", "tractor_registration", "tanker_registration",
            "capacity_litres", "ownership_type", "owner_transporter", "default_driver",
            "status", "is_active", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]
        extra_kwargs = {"internal_id": {"required": False, "allow_blank": True}}
