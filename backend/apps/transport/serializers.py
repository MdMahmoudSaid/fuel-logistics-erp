from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from .models import Driver, Transporter, Truck


class TransporterSerializer(serializers.ModelSerializer):
    gross_earned = serializers.SerializerMethodField()
    deductions = serializers.SerializerMethodField()
    advances_applied = serializers.SerializerMethodField()
    already_paid = serializers.SerializerMethodField()
    net_balance = serializers.SerializerMethodField()

    class Meta:
        model = Transporter
        fields = [
            "id", "name", "company_name", "phone", "address",
            "gross_earned", "deductions", "advances_applied", "already_paid", "net_balance",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_gross_earned(self, obj) -> str:
        total = obj.transport_payments.aggregate(total=Sum("base_amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_deductions(self, obj) -> str:
        total = obj.transport_payments.aggregate(total=Sum("deduction_amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_advances_applied(self, obj) -> str:
        total = sum(
            (
                payment.advance_applied.amount
                for payment in obj.transport_payments.select_related("advance_applied")
                if payment.advance_applied_id
            ),
            Decimal("0.00"),
        )
        return f"{total:.2f}"

    def get_already_paid(self, obj) -> str:
        total = (
            obj.transport_payments.filter(status="PAID").aggregate(total=Sum("net_amount"))["total"]
            or Decimal("0.00")
        )
        return f"{total:.2f}"

    def get_net_balance(self, obj) -> str:
        gross = Decimal(self.get_gross_earned(obj))
        deductions = Decimal(self.get_deductions(obj))
        advances = Decimal(self.get_advances_applied(obj))
        paid = Decimal(self.get_already_paid(obj))
        return f"{gross - deductions - advances - paid:.2f}"


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

    def validate(self, data):
        # Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-
        # phases-design.md): owner_transporter is mandatory for an EXTERNAL
        # truck (a Trip built on it always needs a real transporter to
        # derive) and stays optional for COMPANY_OWNED - never an
        # artificial "internal transporter".
        ownership_type = data.get(
            "ownership_type", getattr(self.instance, "ownership_type", None)
        )
        owner_transporter = (
            data["owner_transporter"]
            if "owner_transporter" in data
            else getattr(self.instance, "owner_transporter", None)
        )
        if ownership_type == Truck.OwnershipType.EXTERNAL and owner_transporter is None:
            raise serializers.ValidationError(
                {
                    "owner_transporter": (
                        "Le transporteur est obligatoire pour un camion externe."
                    )
                }
            )
        return data
