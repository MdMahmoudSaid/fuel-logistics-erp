from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from .models import Driver, Transporter, Truck


def _get_default_internal_transporter() -> Transporter:
    # UI recette fix (2026-09-05): is_internal is now user-editable
    # (TransporterSerializer.validate() below only guarantees "at least
    # one" survives, not "exactly one" - the client's own request implies
    # several internal transporters are expected), so this can no longer
    # be a plain .get() (would crash with MultipleObjectsReturned the
    # moment a second internal transporter exists). Same defensive
    # .filter().first() pattern as Truck.save() below - kept as a small,
    # local helper since both call sites need the identical fallback.
    transporter = Transporter.objects.filter(is_internal=True).first()
    if transporter is None:
        raise serializers.ValidationError(
            {
                "owner_transporter": (
                    "Aucun transporteur interne (flotte propre) n'existe. "
                    "Creez d'abord un transporteur interne."
                )
            }
        )
    return transporter


class TransporterBriefSerializer(serializers.ModelSerializer):
    """A transporter embedded in another record: identity only (see
    CustomerBriefSerializer)."""

    class Meta:
        model = Transporter
        fields = [
            "id", "name", "company_name", "phone", "address",
            "is_active", "is_internal", "created_at", "updated_at",
        ]
        read_only_fields = fields

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
            "is_active", "is_internal", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, data):
        # UI recette fix (2026-09-05): is_internal was read-only, so
        # "Nouveau transporteur / Modifier transporteur" had no way to mark
        # a transporter as internal/external - now writable, but guarded:
        # Truck.save()'s COMPANY_OWNED auto-assign and TruckSerializer's own
        # fallback both do Transporter.objects.filter(is_internal=True) and
        # expect at least one row to exist, so the last internal transporter
        # can never be turned into an external one.
        is_internal = data.get("is_internal", getattr(self.instance, "is_internal", False))
        if self.instance is not None and self.instance.is_internal and not is_internal:
            remaining = (
                Transporter.objects.filter(is_internal=True)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if not remaining:
                raise serializers.ValidationError(
                    {
                        "is_internal": (
                            "Impossible de retirer le dernier transporteur interne "
                            "(flotte propre) - au moins un doit toujours exister."
                        )
                    }
                )
        return data

    def _active_payments(self, obj):
        # Bug fix (2026-09-18): a CANCELLED TransportPayment never really
        # counted - same "reads as what's currently true" rule already
        # applied to TransporterLedgerService.get_ledger - so it must not
        # keep inflating gross_earned/deductions/advances_applied (and, via
        # net_balance, look like an outstanding debt for a trip that was
        # cancelled).
        return obj.transport_payments.exclude(status="CANCELLED")

    def get_gross_earned(self, obj) -> str:
        total = self._active_payments(obj).aggregate(total=Sum("base_amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_deductions(self, obj) -> str:
        total = self._active_payments(obj).aggregate(total=Sum("deduction_amount"))["total"] or Decimal("0.00")
        return f"{total:.2f}"

    def get_advances_applied(self, obj) -> str:
        total = sum(
            (
                payment.advance_applied.amount
                for payment in self._active_payments(obj).select_related("advance_applied")
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
        extra_kwargs = {
            "internal_id": {"required": False, "allow_blank": True},
            # Bug fix (2026-09-03 recette manuelle): the model field is
            # mandatory (NOT NULL), but the API must still accept an
            # omitted owner_transporter for a COMPANY_OWNED truck -
            # validate() auto-assigns the seeded internal transporter in
            # that case. Only an EXTERNAL truck actually requires it in
            # the payload (enforced in validate(), not here).
            "owner_transporter": {"required": False},
        }

    def validate(self, data):
        # Bug fix (2026-09-03 recette manuelle): every truck must be
        # linked to a transporter, with no exception - reverses Phase 6's
        # original "COMPANY_OWNED stays optional" rule. EXTERNAL still
        # requires a real transporter explicitly picked by the user;
        # COMPANY_OWNED auto-assigns the seeded is_internal=True row
        # ("Flotte propre / Interne") when none was provided, so a manager
        # is never blocked entering one, but the invariant ("no truck
        # without a transporter") still always holds.
        ownership_type = data.get(
            "ownership_type", getattr(self.instance, "ownership_type", None)
        )
        owner_transporter = (
            data["owner_transporter"]
            if "owner_transporter" in data
            else getattr(self.instance, "owner_transporter", None)
        )
        if ownership_type == Truck.OwnershipType.EXTERNAL:
            if owner_transporter is None:
                raise serializers.ValidationError(
                    {
                        "owner_transporter": (
                            "Le transporteur est obligatoire pour un camion externe."
                        )
                    }
                )
            if owner_transporter.is_internal:
                raise serializers.ValidationError(
                    {
                        "owner_transporter": (
                            "Le transporteur interne (flotte propre) ne peut pas etre "
                            "assigne a un camion externe."
                        )
                    }
                )
        elif owner_transporter is None:
            data["owner_transporter"] = _get_default_internal_transporter()
        # UI recette fix (2026-09-05): the reverse of the EXTERNAL check
        # above was missing - a COMPANY_OWNED truck could be explicitly
        # assigned an external transporter (only an omitted transporter was
        # ever caught, via the auto-assign branch just above).
        elif not owner_transporter.is_internal:
            raise serializers.ValidationError(
                {
                    "owner_transporter": (
                        "Un camion appartenant a l'entreprise doit avoir un "
                        "transporteur interne (flotte propre)."
                    )
                }
            )
        return data
