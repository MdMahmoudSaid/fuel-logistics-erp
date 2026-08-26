from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.customers.serializers import CustomerSerializer
from apps.suppliers.serializers import SupplierSerializer
from apps.transport.serializers import TransporterSerializer

from .models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    PaymentAllocation,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from .services import FinancePostingService, PaymentAllocationService


class BankAccountSerializer(serializers.ModelSerializer):
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            "id", "name", "bank_name", "account_number", "currency",
            "opening_balance", "current_balance", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CashAccountSerializer(serializers.ModelSerializer):
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = CashAccount
        fields = [
            "id", "name", "location", "currency",
            "opening_balance", "current_balance", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PaymentAllocationSerializer(serializers.ModelSerializer):
    """Read-only nested representation - rows are only ever written by
    PaymentAllocationService.allocate_payment() (guide Section 8.4)."""

    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True, default=None)

    class Meta:
        model = PaymentAllocation
        fields = ["id", "payment", "invoice", "invoice_number", "amount", "created_at"]
        read_only_fields = fields


class InvoiceAllocationInputSerializer(serializers.Serializer):
    """One line of the `allocations` list accepted by CustomerPaymentSerializer
    on create/update - not itself a ModelSerializer, since the row it
    describes is created by PaymentAllocationService, not by DRF directly
    (docs/PHASE_5_PLAN.md Etape 6/7)."""

    invoice = serializers.IntegerField(required=False, allow_null=True, default=None)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))


class CustomerPaymentSerializer(serializers.ModelSerializer):
    """docs/PHASE_5_PLAN.md Etape 7.

    `allocations` is write-only input (a plain list of {invoice, amount})
    consumed by PaymentAllocationService.allocate_payment() in create()/
    update() - the actual PaymentAllocation rows it produces are exposed
    back out read-only as `allocations_detail`, so one request can both
    record the payment and immediately imbue/split it across invoices
    (guide Section 8.2: "avec liste d'allocations imbriquee").
    """

    customer_detail = CustomerSerializer(source="customer", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    allocations_detail = PaymentAllocationSerializer(source="allocations", many=True, read_only=True)
    allocations = InvoiceAllocationInputSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = CustomerPayment
        fields = [
            "id", "customer", "customer_detail", "amount", "payment_date", "method",
            "bank_account", "cash_account", "reference", "is_indirect", "destination", "note",
            "recorded_by", "recorded_by_detail",
            "allocations", "allocations_detail",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def validate(self, data):
        """`destination` is the single source of truth for is_indirect/
        bank_account/cash_account (Task 4, client modifications plan,
        ruling 1): the client only ever needs to send `destination` plus,
        for BANK/CASH, the matching account - is_indirect and the "other"
        account are always derived here, so the two concepts can never
        disagree with each other regardless of what the client actually
        sent.
        """
        destination = data.get(
            "destination", getattr(self.instance, "destination", CustomerPayment.Destination.CASH)
        )

        if destination == CustomerPayment.Destination.INDIRECT:
            data["is_indirect"] = True
            data["bank_account"] = None
            data["cash_account"] = None
        elif destination == CustomerPayment.Destination.BANK:
            data["is_indirect"] = False
            data["cash_account"] = None
            bank_account = data.get("bank_account", getattr(self.instance, "bank_account", None))
            if not bank_account:
                raise serializers.ValidationError(
                    {"bank_account": "Un compte bancaire est requis pour la destination Banque."}
                )
            data["bank_account"] = bank_account
        elif destination == CustomerPayment.Destination.CASH:
            data["is_indirect"] = False
            data["bank_account"] = None
            cash_account = data.get("cash_account", getattr(self.instance, "cash_account", None))
            if not cash_account:
                raise serializers.ValidationError(
                    {"cash_account": "Un compte de caisse est requis pour la destination Caisse."}
                )
            if cash_account.name == FinancePostingService.VERS_MOI_ACCOUNT_NAME:
                raise serializers.ValidationError(
                    {"cash_account": "Utilisez la destination 'Vers moi' pour ce compte."}
                )
            data["cash_account"] = cash_account
        elif destination == CustomerPayment.Destination.VERS_MOI:
            data["is_indirect"] = False
            data["bank_account"] = None
            data["cash_account"] = FinancePostingService.get_or_create_vers_moi_account()
        else:
            raise serializers.ValidationError({"destination": "Destination inconnue."})

        data["destination"] = destination
        return data

    def create(self, validated_data):
        allocations = validated_data.pop("allocations", [])
        with transaction.atomic():
            payment = CustomerPayment.objects.create(**validated_data)
            if allocations:
                PaymentAllocationService.allocate_payment(payment.id, allocations)
            FinancePostingService.record_customer_payment_treasury(payment)
        payment.refresh_from_db()
        return payment

    def update(self, instance, validated_data):
        allocations = validated_data.pop("allocations", [])
        payment = super().update(instance, validated_data)
        if allocations:
            PaymentAllocationService.allocate_payment(payment.id, allocations)
        payment.refresh_from_db()
        return payment


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSerializer(source="supplier", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)

    class Meta:
        model = SupplierPayment
        fields = [
            "id", "supplier", "supplier_detail", "supplier_order", "amount", "payment_date",
            "method", "bank_account", "cash_account", "is_advance", "reference",
            "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def validate(self, data):
        bank_account = data.get("bank_account", getattr(self.instance, "bank_account", None))
        cash_account = data.get("cash_account", getattr(self.instance, "cash_account", None))
        if bank_account and cash_account:
            raise serializers.ValidationError(
                "Un seul compte (banque OU caisse) peut etre renseigne."
            )
        if not bank_account and not cash_account:
            raise serializers.ValidationError(
                "Un compte de tresorerie (banque ou caisse) est requis."
            )
        return data


class TransporterAdvanceSerializer(serializers.ModelSerializer):
    transporter_detail = TransporterSerializer(source="transporter", read_only=True)

    class Meta:
        model = TransporterAdvance
        fields = [
            "id", "transporter", "transporter_detail", "amount", "date",
            "reference", "notes", "settled", "created_at", "updated_at",
        ]
        # settled is flipped exclusively by TransportPayment.save() once a
        # payment consumes this advance - never a direct client write.
        read_only_fields = ["id", "settled", "created_at", "updated_at"]


class TransportPaymentSerializer(serializers.ModelSerializer):
    transporter_detail = TransporterSerializer(source="transporter", read_only=True)
    trip_reference = serializers.CharField(source="trip.reference", read_only=True)
    net_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = TransportPayment
        fields = [
            "id", "trip", "trip_reference", "transporter", "transporter_detail",
            "calculation_method", "base_amount", "unit_price_per_litre", "deduction_amount",
            "advance_applied", "net_amount", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "net_amount", "created_at", "updated_at"]
        extra_kwargs = {"base_amount": {"required": False}}

    def validate(self, data):
        advance = data.get("advance_applied", getattr(self.instance, "advance_applied", None))
        transporter = data.get("transporter", getattr(self.instance, "transporter", None))
        trip = data.get("trip", getattr(self.instance, "trip", None))
        calculation_method = data.get(
            "calculation_method", getattr(self.instance, "calculation_method", None)
        )
        unit_price_per_litre = data.get(
            "unit_price_per_litre", getattr(self.instance, "unit_price_per_litre", None)
        )

        if advance and transporter and advance.transporter_id != transporter.id:
            raise serializers.ValidationError(
                "L'avance selectionnee n'appartient pas a ce transporteur."
            )

        if trip and transporter and transporter.id != trip.transporter_id:
            raise serializers.ValidationError(
                "Le transporteur ne correspond pas au transporteur du voyage."
            )

        if calculation_method == TransportPayment.CalculationMethod.PER_LITRE:
            if unit_price_per_litre is None:
                raise serializers.ValidationError(
                    {"unit_price_per_litre": "Le prix par litre est requis pour ce mode de calcul."}
                )
            if trip is None:
                raise serializers.ValidationError(
                    {"trip": "Le voyage est requis pour calculer le montant au litre."}
                )
            # base_amount is derived, never trusted from client input (guide:
            # transport cost per litre must create/update the transporter
            # payable line automatically).
            data["base_amount"] = (trip.quantity_loaded * unit_price_per_litre).quantize(
                Decimal("0.01")
            )
        elif data.get("base_amount") is None and getattr(self.instance, "base_amount", None) is None:
            raise serializers.ValidationError(
                {"base_amount": "Ce champ est obligatoire."}
            )

        return data


class ExpenseAllocationSerializer(serializers.ModelSerializer):
    content_type_name = serializers.CharField(source="content_type.model", read_only=True, default=None)
    content_object_repr = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseAllocation
        fields = [
            "id", "expense", "content_type", "content_type_name", "object_id",
            "content_object_repr", "allocated_amount", "created_at",
        ]
        read_only_fields = ["id", "expense", "created_at"]

    def get_content_object_repr(self, obj) -> str:
        return str(obj.content_object) if obj.content_object else ""


class ExpenseAllocationInputSerializer(serializers.Serializer):
    """Write path for one ExpenseAllocation line nested under ExpenseSerializer
    (docs/PHASE_5_PLAN.md Etape 7: "un frais de douane peut impacter
    plusieurs trajets")."""

    content_type = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.all(), required=False, allow_null=True, default=None
    )
    object_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    allocated_amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))


class ExpenseSerializer(serializers.ModelSerializer):
    allocations_detail = ExpenseAllocationSerializer(source="allocations", many=True, read_only=True)
    allocations = ExpenseAllocationInputSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = Expense
        fields = [
            "id", "category", "amount", "calculation_method", "date", "status",
            "paid_by_customer_directly", "notes",
            "allocations", "allocations_detail", "created_at", "updated_at",
        ]
        # paid_by_customer_directly/status=PAID for the indirect case is only
        # ever set by IndirectSettlementService, never a direct client write.
        read_only_fields = ["id", "paid_by_customer_directly", "created_at", "updated_at"]

    def create(self, validated_data):
        allocations = validated_data.pop("allocations", [])
        expense = Expense.objects.create(**validated_data)
        for item in allocations:
            ExpenseAllocation.objects.create(expense=expense, **item)
        return expense

    def update(self, instance, validated_data):
        allocations = validated_data.pop("allocations", [])
        expense = super().update(instance, validated_data)
        for item in allocations:
            ExpenseAllocation.objects.create(expense=expense, **item)
        return expense


class IndirectSettlementRequestSerializer(serializers.Serializer):
    """Input for POST /api/expenses/record-indirect/ (docs/PHASE_5_PLAN.md
    Etape 6/7; guide Section 1.6/8.9). Not a ModelSerializer: the Expense +
    CustomerPayment + PaymentAllocation triple is created exclusively by
    IndirectSettlementService.record_indirect_payment()."""

    customer = serializers.IntegerField()
    invoice = serializers.IntegerField(required=False, allow_null=True, default=None)
    category = serializers.ChoiceField(choices=Expense.Category.choices)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
    calculation_method = serializers.ChoiceField(
        choices=Expense.CalculationMethod.choices, default=Expense.CalculationMethod.MANUAL
    )
    date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class TreasuryTransactionSerializer(serializers.ModelSerializer):
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    source_object_repr = serializers.SerializerMethodField()

    class Meta:
        model = TreasuryTransaction
        fields = [
            "id", "bank_account", "cash_account", "type", "is_transfer", "amount", "date",
            "reference", "source_content_type", "source_object_id", "source_object_repr",
            "document", "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        # is_transfer is only ever set by TreasuryService.record_transfer() -
        # a direct client create always produces a plain (non-transfer)
        # MONEY_IN/MONEY_OUT row; internal transfers must go through
        # POST /api/treasury-transactions/transfer/.
        read_only_fields = ["id", "is_transfer", "recorded_by", "created_at", "updated_at"]

    def get_source_object_repr(self, obj) -> str:
        return str(obj.source_object) if obj.source_object else ""

    def validate(self, data):
        bank_account = data.get("bank_account", getattr(self.instance, "bank_account", None))
        cash_account = data.get("cash_account", getattr(self.instance, "cash_account", None))
        if bank_account and cash_account:
            raise serializers.ValidationError(
                "Un seul compte (banque OU caisse) peut etre renseigne."
            )
        if not bank_account and not cash_account:
            raise serializers.ValidationError(
                "Un compte de tresorerie (banque ou caisse) est requis."
            )
        return data


class TreasuryTransferRequestSerializer(serializers.Serializer):
    """Input for POST /api/treasury-transactions/transfer/
    (docs/PHASE_5_PLAN.md Etape 7: "Interdire les transferts vers le meme
    compte")."""

    source_account_type = serializers.ChoiceField(choices=["bank", "cash"])
    source_account_id = serializers.IntegerField()
    dest_account_type = serializers.ChoiceField(choices=["bank", "cash"])
    dest_account_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
    date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        if (
            data["source_account_type"] == data["dest_account_type"]
            and data["source_account_id"] == data["dest_account_id"]
        ):
            raise serializers.ValidationError(
                "Impossible de transferer un compte vers lui-meme."
            )
        return data
