import json
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils.text import slugify
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.customers.serializers import CustomerSerializer
from apps.documents.models import Document
from apps.documents.validators import validate_image_upload
from apps.finance.labels import describe_treasury_transaction
from apps.suppliers.serializers import SupplierSerializer
from apps.transport.serializers import TransporterSerializer
from apps.trips.models import Trip

from .models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    ExpenseCategory,
    PaymentAllocation,
    Shareholder,
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    SupplierAdvance,
    SupplierPayment,
    TransporterAdvance,
    TransportPayment,
    TreasuryTransaction,
)
from .services import (
    AdvanceError,
    AdvanceService,
    ControlledDebtPaymentService,
    FinancePostingService,
    PaymentAllocationService,
    ShareholderContributionError,
    ShareholderContributionService,
    ShareholderDistributionService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderParticipationError,
    ShareholderService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
)


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
    proof_url = serializers.SerializerMethodField()
    proof = serializers.FileField(write_only=True, required=False, allow_null=True)

    def to_internal_value(self, data):
        if hasattr(data, "lists"):
            data = {
                key: values[-1] if len(values) == 1 else values
                for key, values in data.lists()
            }
        elif hasattr(data, "copy"):
            data = data.copy()
        allocations = data.get("allocations") if hasattr(data, "get") else None
        if isinstance(allocations, str):
            try:
                data["allocations"] = json.loads(allocations)
            except json.JSONDecodeError:
                raise serializers.ValidationError(
                    {"allocations": "Format de repartition invalide."}
                )
        return super().to_internal_value(data)

    class Meta:
        model = CustomerPayment
        fields = [
            "id", "customer", "customer_detail", "amount", "payment_date", "method",
            "bank_account", "cash_account", "reference", "is_indirect", "destination", "note",
            "recorded_by", "recorded_by_detail",
            "allocations", "allocations_detail", "proof", "proof_url",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        content_type = ContentType.objects.get_for_model(CustomerPayment)
        document = (
            Document.objects.filter(
                content_type=content_type,
                object_id=obj.id,
                document_type="customer_payment_proof",
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if not document or not document.file:
            return None
        return document.file.url

    def validate_proof(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

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
        if self.instance is None and not data.get("proof"):
            raise serializers.ValidationError(
                {"proof": "Le justificatif de paiement est obligatoire."}
            )
        return data

    def create(self, validated_data):
        allocations = validated_data.pop("allocations", [])
        proof = validated_data.pop("proof", None)
        with transaction.atomic():
            payment = CustomerPayment.objects.create(**validated_data)
            content_type = ContentType.objects.get_for_model(CustomerPayment)
            document = Document.objects.create(
                file=proof,
                document_type="customer_payment_proof",
                uploaded_by=payment.recorded_by,
                content_type=content_type,
                object_id=payment.id,
            )
            if allocations:
                PaymentAllocationService.allocate_payment(payment.id, allocations)
            FinancePostingService.record_customer_payment_treasury(payment, document=document)
        payment.refresh_from_db()
        return payment

    def update(self, instance, validated_data):
        allocations = validated_data.pop("allocations", [])
        validated_data.pop("proof", None)
        payment = super().update(instance, validated_data)
        if allocations:
            PaymentAllocationService.allocate_payment(payment.id, allocations)
        payment.refresh_from_db()
        return payment


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSerializer(source="supplier", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    proof_url = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPayment
        fields = [
            "id", "supplier", "supplier_detail", "supplier_order", "amount", "payment_date",
            "method", "bank_account", "cash_account", "is_advance", "reference",
            "recorded_by", "recorded_by_detail", "proof_url", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        payment_content_type = ContentType.objects.get_for_model(SupplierPayment)
        txn = (
            TreasuryTransaction.objects.filter(
                source_content_type=payment_content_type,
                source_object_id=obj.id,
                document__isnull=False,
            )
            .select_related("document")
            .order_by("-date", "-id")
            .first()
        )
        if txn is None or not txn.document.file:
            return None
        return txn.document.file.url

    def validate(self, data):
        bank_account = data.get("bank_account", getattr(self.instance, "bank_account", None))
        cash_account = data.get("cash_account", getattr(self.instance, "cash_account", None))
        is_advance = data.get("is_advance", getattr(self.instance, "is_advance", False))
        method = data.get("method", getattr(self.instance, "method", None))

        if self.instance is None and is_advance:
            raise serializers.ValidationError(
                {
                    "is_advance": (
                        "Utilisez POST /api/supplier-advances/ pour creer une nouvelle "
                        "avance fournisseur."
                    )
                }
            )

        if bank_account and cash_account:
            raise serializers.ValidationError(
                "Un seul compte (banque OU caisse) peut etre renseigne."
            )
        if not bank_account and not cash_account:
            raise serializers.ValidationError(
                "Un compte de tresorerie (banque ou caisse) est requis."
            )

        if not is_advance:
            # Task 5 (client modifications plan): a supplier debt repayment
            # (is_advance=False) must move through a bank account by bank
            # transfer - no cash settlement for that flow. Advances
            # (is_advance=True) are exempt from this restriction (ruling 1
            # of the task dispatch) - they may still use cash or another
            # account, per the base exclusivity rule above.
            if method != SupplierPayment.Method.BANK_TRANSFER:
                raise serializers.ValidationError(
                    {
                        "method": (
                            "Le remboursement d'une dette fournisseur doit "
                            "utiliser un virement bancaire."
                        )
                    }
                )
            if not bank_account:
                raise serializers.ValidationError(
                    {
                        "bank_account": (
                            "Un compte bancaire est requis pour le remboursement "
                            "d'une dette fournisseur."
                        )
                    }
                )
            if cash_account:
                raise serializers.ValidationError(
                    {
                        "cash_account": (
                            "Un compte de caisse n'est pas autorise pour le "
                            "remboursement d'une dette fournisseur."
                        )
                    }
                )

        return data

    def create(self, validated_data):
        with transaction.atomic():
            payment = SupplierPayment.objects.create(**validated_data)
            FinancePostingService.record_supplier_payment_treasury(payment)
        payment.refresh_from_db()
        return payment

    def update(self, instance, validated_data):
        # Ruling 3 (Task 5, client modifications plan): every SupplierPayment
        # is already posted to treasury synchronously inside create()'s
        # atomic block above, so there is no meaningful "unposted" state to
        # distinguish - every existing row is already posted. Block the edit
        # entirely until a reversal/correction flow is designed, rather than
        # silently mutating finalized financial history.
        raise serializers.ValidationError(
            "Un paiement fournisseur enregistre ne peut pas etre modifie."
        )


class SupplierAdvanceSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSerializer(source="supplier", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = SupplierAdvance
        fields = [
            "id", "supplier", "supplier_detail", "bank_account", "cash_account",
            "amount", "date", "reference", "notes", "attachment", "proof_url",
            "remaining_amount", "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "remaining_amount", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account and not cash_account:
            raise serializers.ValidationError("Un compte de tresorerie (banque ou caisse) est requis.")
        if self.instance is None and not data.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "Un justificatif image est obligatoire pour creer une avance."}
            )
        return data

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return AdvanceService.create_supplier_advance(
                supplier_id=validated_data["supplier"].id,
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                amount=validated_data["amount"],
                date=validated_data["date"],
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
                attachment=validated_data["attachment"],
                actor=actor,
            )
        except AdvanceError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Une avance enregistree ne peut pas etre modifiee.")


class TransporterAdvanceSerializer(serializers.ModelSerializer):
    transporter_detail = TransporterSerializer(source="transporter", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = TransporterAdvance
        fields = [
            "id", "transporter", "transporter_detail", "bank_account", "cash_account",
            "amount", "date", "reference", "notes", "attachment", "proof_url",
            "remaining_amount", "settled", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "remaining_amount", "settled", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account and not cash_account:
            raise serializers.ValidationError("Un compte de tresorerie (banque ou caisse) est requis.")
        if self.instance is None and not data.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "Un justificatif image est obligatoire pour creer une avance."}
            )
        return data

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return AdvanceService.create_transporter_advance(
                transporter_id=validated_data["transporter"].id,
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                amount=validated_data["amount"],
                date=validated_data["date"],
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
                attachment=validated_data["attachment"],
                actor=actor,
            )
        except AdvanceError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Une avance enregistree ne peut pas etre modifiee.")


class TransportPaymentSerializer(serializers.ModelSerializer):
    transporter_detail = TransporterSerializer(source="transporter", read_only=True)
    trip_reference = serializers.CharField(source="trip.reference", read_only=True)
    net_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    deduction_label = serializers.SerializerMethodField()

    class Meta:
        model = TransportPayment
        fields = [
            "id", "trip", "trip_reference", "transporter", "transporter_detail",
            "calculation_method", "base_amount", "unit_price_per_litre", "deduction_amount",
            "deduction_label", "advance_applied", "net_amount", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "net_amount", "advance_applied", "created_at", "updated_at"]
        extra_kwargs = {"base_amount": {"required": False}}

    def validate(self, data):
        transporter = data.get("transporter", getattr(self.instance, "transporter", None))
        trip = data.get("trip", getattr(self.instance, "trip", None))
        calculation_method = data.get(
            "calculation_method", getattr(self.instance, "calculation_method", None)
        )
        unit_price_per_litre = data.get(
            "unit_price_per_litre", getattr(self.instance, "unit_price_per_litre", None)
        )

        # Bug fix (2026-09-03 recette manuelle): a company-owned truck's
        # trip is now linked to the seeded internal transporter (never
        # None) rather than left blank, but it still must never receive a
        # real transport payment - flotte propre has no external debt to
        # settle. trip.transporter_id is None is kept as a defensive
        # fallback for any trip that predates this fix.
        if trip and (trip.transporter_id is None or trip.transporter.is_internal):
            raise serializers.ValidationError(
                "Ce trajet n'a pas de transporteur externe, aucun paiement "
                "transport n'est possible."
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

    def get_deduction_label(self, obj) -> str:
        deduction = obj.trip.transport_deductions.order_by("-created_at", "-id").first()
        if deduction is None:
            return ""
        return (
            f"Manque quantite - {obj.trip.reference} - "
            f"{deduction.chargeable_quantity} L x {deduction.unit_price} XOF/L"
        )


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


class ExpenseCategorySerializer(serializers.ModelSerializer):
    code = serializers.SlugField(max_length=30, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "code", "is_system", "is_active", "display_order"]
        read_only_fields = ["id", "is_system"]

    def validate(self, data):
        if self.instance is not None and self.instance.is_system:
            changed_fields = {
                key
                for key, value in data.items()
                if key != "is_system" and getattr(self.instance, key) != value
            }
            if changed_fields:
                raise serializers.ValidationError(
                    "Une categorie systeme ne peut pas etre modifiee."
                )
        return data

    def create(self, validated_data):
        if not validated_data.get("code"):
            validated_data["code"] = self._generate_unique_code(validated_data["name"])
        return super().create(validated_data)

    def _generate_unique_code(self, name: str) -> str:
        base = slugify(name).replace("-", "_")[:30].strip("_") or "category"
        code = base
        suffix = 2
        while ExpenseCategory.objects.filter(code=code).exists():
            suffix_text = f"_{suffix}"
            code = f"{base[:30 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        return code


class ExpenseSerializer(serializers.ModelSerializer):
    # Phase 5 (docs/superpowers/specs/2026-09-02-business-corrections-6-
    # phases-design.md): a trip-allocated fee only ever uses one of these
    # two methods - other methods (FIXED, PERCENTAGE, PER_ORDER, MANUAL)
    # stay available for general (unallocated) expenses, unchanged.
    _TRIP_CALCULATION_METHODS = {
        Expense.CalculationMethod.PER_LITRE,
        Expense.CalculationMethod.PER_TRUCK,
    }
    # Locked once PAID/PARTIALLY_PAID - only /cancel/ (ExpensePostingService.
    # cancel_paid_expense) may unwind a fee past that point.
    _SENSITIVE_FIELDS_LOCKED_WHEN_PAID = ("amount", "calculation_method", "category", "allocations")

    allocations_detail = ExpenseAllocationSerializer(source="allocations", many=True, read_only=True)
    allocations = ExpenseAllocationInputSerializer(many=True, write_only=True, required=False)
    category = serializers.CharField()
    bank_account = serializers.PrimaryKeyRelatedField(
        queryset=BankAccount.objects.all(), write_only=True, required=False, allow_null=True
    )
    cash_account = serializers.PrimaryKeyRelatedField(
        queryset=CashAccount.objects.all(), write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Expense
        fields = [
            "id", "category", "amount", "calculation_method", "date", "status",
            "paid_by_customer_directly", "notes",
            "allocations", "allocations_detail", "bank_account", "cash_account",
            "created_at", "updated_at",
        ]
        # paid_by_customer_directly/status=PAID for the indirect case is only
        # ever set by IndirectSettlementService, never a direct client write.
        read_only_fields = ["id", "paid_by_customer_directly", "created_at", "updated_at"]

    def validate_category(self, value):
        if not ExpenseCategory.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("Categorie de depense invalide ou inactive.")
        return value

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError(
                "Un seul compte (banque OU caisse) peut etre renseigne."
            )
        if (bank_account or cash_account) and data.get("allocations"):
            raise serializers.ValidationError(
                "Le paiement direct est reserve aux depenses generales sans repartition."
            )

        if self.instance is not None and self.instance.status in (
            Expense.Status.PAID,
            Expense.Status.PARTIALLY_PAID,
        ):
            locked_changed = any(
                field in data for field in self._SENSITIVE_FIELDS_LOCKED_WHEN_PAID
            )
            status_changed = "status" in data and data["status"] != self.instance.status
            if locked_changed or status_changed:
                raise serializers.ValidationError(
                    "Ce frais est deja paye (totalement ou partiellement) : "
                    "utilisez l'annulation pour le modifier."
                )

        calculation_method = data.get(
            "calculation_method", getattr(self.instance, "calculation_method", None)
        )
        allocations = data.get("allocations")
        if allocations:
            trip_content_type = ContentType.objects.get_for_model(Trip)
            targets_trip = any(
                item.get("content_type") == trip_content_type for item in allocations
            )
            if targets_trip and calculation_method not in self._TRIP_CALCULATION_METHODS:
                raise serializers.ValidationError(
                    "Pour un frais alloue a un trajet, seules les methodes "
                    "'Par litre' ou 'Par camion' sont autorisees."
                )
        return data

    def _resolve_allocated_amount(self, item, calculation_method, amount):
        # Server-authoritative for a Trip target: PER_LITRE's "amount" is a
        # XOF/L rate (total = rate x trip.quantity_loaded), PER_TRUCK's
        # "amount" is already the total (unmultiplied) - never trust
        # whatever allocated_amount the client happened to send for these,
        # only for other allocatable kinds (truck/customer/supplier/
        # transporter) or other calculation methods, unchanged.
        if item.get("content_type") != ContentType.objects.get_for_model(Trip):
            return item["allocated_amount"]
        if calculation_method not in self._TRIP_CALCULATION_METHODS:
            return item["allocated_amount"]
        trip = Trip.objects.get(pk=item["object_id"])
        if calculation_method == Expense.CalculationMethod.PER_LITRE:
            return (amount * trip.quantity_loaded).quantize(Decimal("0.01"))
        return amount

    def create(self, validated_data):
        allocations = validated_data.pop("allocations", [])
        bank_account = validated_data.pop("bank_account", None)
        cash_account = validated_data.pop("cash_account", None)
        paid_directly = bank_account is not None or cash_account is not None
        if paid_directly:
            validated_data["status"] = Expense.Status.PAID
        with transaction.atomic():
            expense = Expense.objects.create(**validated_data)
            for item in allocations:
                ExpenseAllocation.objects.create(
                    expense=expense,
                    **{
                        **item,
                        "allocated_amount": self._resolve_allocated_amount(
                            item, expense.calculation_method, expense.amount
                        ),
                    },
                )
            if paid_directly:
                TreasuryTransaction.objects.create(
                    bank_account=bank_account,
                    cash_account=cash_account,
                    type=TreasuryTransaction.Type.MONEY_OUT,
                    amount=expense.amount,
                    date=expense.date,
                    note=expense.notes,
                    source_content_type=ContentType.objects.get_for_model(Expense),
                    source_object_id=expense.id,
                    recorded_by=self.context["request"].user,
                )
        return expense

    def update(self, instance, validated_data):
        allocations = validated_data.pop("allocations", [])
        expense = super().update(instance, validated_data)
        for item in allocations:
            ExpenseAllocation.objects.create(
                expense=expense,
                **{
                    **item,
                    "allocated_amount": self._resolve_allocated_amount(
                        item, expense.calculation_method, expense.amount
                    ),
                },
            )
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
    bank_account_name = serializers.SerializerMethodField()
    cash_account_name = serializers.SerializerMethodField()
    counterparty = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()

    class Meta:
        model = TreasuryTransaction
        fields = [
            "id", "bank_account", "bank_account_name", "cash_account", "cash_account_name",
            "type", "is_transfer", "amount", "date",
            "reference", "note", "source_content_type", "source_object_id", "source_object_repr",
            "counterparty",
            "document", "document_url", "recorded_by", "recorded_by_detail",
            "created_at", "updated_at",
        ]
        # is_transfer is only ever set by TreasuryService.record_transfer() -
        # a direct client create always produces a plain (non-transfer)
        # MONEY_IN/MONEY_OUT row; internal transfers must go through
        # POST /api/treasury-transactions/transfer/.
        read_only_fields = ["id", "is_transfer", "recorded_by", "created_at", "updated_at"]

    def get_source_object_repr(self, obj) -> str:
        return str(obj.source_object) if obj.source_object else ""

    def get_bank_account_name(self, obj) -> str | None:
        return obj.bank_account.name if obj.bank_account_id else None

    def get_cash_account_name(self, obj) -> str | None:
        return obj.cash_account.name if obj.cash_account_id else None

    def get_counterparty(self, obj) -> str | None:
        return describe_treasury_transaction(obj)["counterparty"]

    def get_document_url(self, obj) -> str | None:
        # Deliberately root-relative (never request.build_absolute_uri()):
        # in the dev/docker-compose topology the frontend only proxies
        # /api and /media to the backend container, so an absolute URL
        # would bake in the backend's internal Host header (e.g.
        # "backend:8000") and be unreachable from the browser. A
        # same-origin path lets the browser resolve it against whatever
        # host actually served the page, exactly like /api calls already
        # do via apiClient's baseURL.
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

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


class ControlledDebtPaymentRequestSerializer(serializers.Serializer):
    """Input for POST /api/treasury-transactions/record-debt-payment/.

    The serializer handles shape/type validation only; the cross-row
    financial rules live in ControlledDebtPaymentService.
    """

    debt_type = serializers.ChoiceField(
        choices=[(value, value) for value in ControlledDebtPaymentService.supported_debt_types()]
    )
    debt_id = serializers.IntegerField()
    bank_account = serializers.IntegerField()
    amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=Decimal("0.01")
    )
    date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    attachment = serializers.FileField(required=False, allow_null=True, default=None)

    def validate(self, data):
        if not data.get("attachment"):
            raise serializers.ValidationError(
                {
                    "attachment": (
                        "Un justificatif image est obligatoire pour enregistrer ce paiement."
                    )
                }
            )
        return data

    def validate_attachment(self, value):
        if value is None:
            raise serializers.ValidationError(
                "Un justificatif image est obligatoire pour enregistrer ce paiement."
            )
        return validate_image_upload(value)


# ---------------------------------------------------------------------------
# Task 7 (client modifications plan): Shareholders / Associates domain
# ---------------------------------------------------------------------------


class ShareholderBriefSerializer(serializers.ModelSerializer):
    """Compact nested representation for borrower/lender/shareholder
    references, same role as CustomerBrief/SupplierBrief elsewhere in this
    module."""

    class Meta:
        model = Shareholder
        fields = ["id", "name", "participation_percent", "contribution"]


class ShareholderSerializer(serializers.ModelSerializer):
    # Real cash actually put in via ShareholderContribution (Phase 1),
    # distinct from `contribution` (a historical opening-balance figure set
    # at Shareholder creation, never updated by new contributions - see
    # spec 2026-09-02-business-corrections-6-phases-design.md Phase 1).
    # Annotated on ShareholderViewSet.queryset; falls back to a live
    # aggregate when the serializer is used without that annotation (e.g.
    # nested elsewhere) so this field is never silently wrong.
    total_contributed = serializers.SerializerMethodField()

    class Meta:
        model = Shareholder
        fields = [
            "id", "name", "participation_percent", "contribution", "total_contributed",
            "phone", "notes", "is_active", "created_at", "updated_at",
        ]

    def get_total_contributed(self, obj) -> str:
        annotated = getattr(obj, "total_contributed", None)
        value = (
            annotated
            if annotated is not None
            else obj.contributions.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )
        # Match every other DecimalField on this serializer (DRF renders
        # those as strings) - a SerializerMethodField doesn't get that
        # coercion for free, and this value feeds straight into a money
        # display on the frontend.
        return str(value.quantize(Decimal("0.01")))
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, data):
        """Active shareholder percentages cannot exceed 100 total (Task 7
        design guidance) - a cross-row rule PostgreSQL can't enforce as a
        single-row CheckConstraint, so it lives in
        ShareholderService.validate_total_participation(), called here
        before create/update of an active shareholder."""
        is_active = data.get("is_active", getattr(self.instance, "is_active", True))
        percent = data.get(
            "participation_percent", getattr(self.instance, "participation_percent", None)
        )
        if is_active and percent is not None:
            exclude_id = self.instance.id if self.instance is not None else None
            try:
                ShareholderService.validate_total_participation(percent, exclude_id=exclude_id)
            except ShareholderParticipationError as exc:
                raise serializers.ValidationError({"participation_percent": str(exc)})
        return data


class ShareholderProfitShareSerializer(serializers.ModelSerializer):
    """Read-only - rows are only ever created by
    ShareholderDistributionService.create_distribution()."""

    shareholder_detail = ShareholderBriefSerializer(source="shareholder", read_only=True)
    remaining_due = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = ShareholderProfitShare
        fields = [
            "id", "distribution", "shareholder", "shareholder_detail",
            "percent_snapshot", "amount_due", "amount_withdrawn", "remaining_due",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class ShareholderProfitDistributionSerializer(serializers.ModelSerializer):
    """docs/Task 7 (client modifications plan).

    Creation is delegated entirely to
    ShareholderDistributionService.create_distribution(): the client only
    ever sends period_start/period_end/total_profit, and the DRAFT
    distribution plus its snapshotted ShareholderProfitShare rows come back
    read-only in `shares`. Like SupplierPaymentSerializer, update() is
    blocked - once created, a distribution moves forward only via the
    dedicated `validate` action, never a plain PATCH.
    """

    created_by_detail = UserSerializer(source="created_by", read_only=True)
    validated_by_detail = UserSerializer(source="validated_by", read_only=True)
    shares = ShareholderProfitShareSerializer(many=True, read_only=True)

    class Meta:
        model = ShareholderProfitDistribution
        fields = [
            "id", "period_start", "period_end", "total_profit", "status",
            "created_by", "created_by_detail", "validated_by", "validated_by_detail",
            "validated_at", "shares", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "created_by", "validated_by", "validated_at",
            "created_at", "updated_at",
        ]

    def create(self, validated_data):
        actor = self.context["request"].user
        return ShareholderDistributionService.create_distribution(
            period_start=validated_data["period_start"],
            period_end=validated_data["period_end"],
            total_profit=validated_data["total_profit"],
            actor=actor,
        )

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Une distribution ne peut pas etre modifiee ; utilisez l'action 'valider'."
        )


class ShareholderLoanSerializer(serializers.ModelSerializer):
    borrower_detail = ShareholderBriefSerializer(source="borrower", read_only=True)
    lender_detail = ShareholderBriefSerializer(source="lender", read_only=True)
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = ShareholderLoan
        fields = [
            "id", "borrower", "borrower_detail", "lender", "lender_detail",
            "amount", "date", "status", "amount_repaid", "remaining_amount", "notes",
            "created_at", "updated_at",
        ]
        # status is derived in ShareholderLoan.save() from amount_repaid vs
        # amount - never a direct client write (same convention as
        # TransporterAdvance.settled). amount_repaid itself is also
        # read-only here (Task 7 fix: loan-repayment lost-update race) -
        # a client PATCHing an absolute amount_repaid computed from a
        # stale read can silently overwrite a concurrent repayment.
        # The only way to change it is
        # ShareholderLoanService.record_repayment() via the dedicated
        # record-repayment action, which increments it under
        # select_for_update().
        read_only_fields = ["id", "status", "amount_repaid", "created_at", "updated_at"]

    def validate(self, data):
        borrower = data.get("borrower", getattr(self.instance, "borrower", None))
        lender = data.get("lender", getattr(self.instance, "lender", None))

        if borrower and lender and borrower.id == lender.id:
            raise serializers.ValidationError(
                "L'emprunteur et le preteur ne peuvent pas etre le meme actionnaire."
            )
        return data

    def create(self, validated_data):
        try:
            return ShareholderLoanService.create_loan(
                borrower_id=validated_data["borrower"].id,
                lender_id=validated_data["lender"].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                notes=validated_data.get("notes", ""),
            )
        except ShareholderLoanError as exc:
            raise serializers.ValidationError(str(exc))


class ShareholderWithdrawalSerializer(serializers.ModelSerializer):
    """Creation is delegated to ShareholderWithdrawalService.record_withdrawal()
    (Task 7, client modifications plan) - it, not this serializer, owns the
    remaining-due check against profit_share, the amount_withdrawn
    reconciliation, and the TreasuryTransaction(MONEY_OUT) posting, all
    under one row lock."""

    shareholder_detail = ShareholderBriefSerializer(source="shareholder", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)

    class Meta:
        model = ShareholderWithdrawal
        fields = [
            "id", "shareholder", "shareholder_detail", "profit_share", "amount", "date",
            "bank_account", "cash_account", "notes",
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

        profit_share = data.get("profit_share", getattr(self.instance, "profit_share", None))
        shareholder = data.get("shareholder", getattr(self.instance, "shareholder", None))
        if profit_share and shareholder and profit_share.shareholder_id != shareholder.id:
            raise serializers.ValidationError(
                {"profit_share": "Cette part de benefice n'appartient pas a cet actionnaire."}
            )
        return data

    def create(self, validated_data):
        actor = self.context["request"].user
        profit_share = validated_data.get("profit_share")
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return ShareholderWithdrawalService.record_withdrawal(
                shareholder_id=validated_data["shareholder"].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                actor=actor,
                profit_share_id=profit_share.id if profit_share else None,
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                notes=validated_data.get("notes", ""),
            )
        except ShareholderWithdrawalError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Un retrait enregistre ne peut pas etre modifie."
        )


class ShareholderContributionSerializer(serializers.ModelSerializer):
    """Creation is delegated to
    ShareholderContributionService.record_contribution() (Phase 1) - it,
    not this serializer, owns the Document creation and the
    TreasuryTransaction(MONEY_IN) posting, both under one row lock."""

    shareholder_detail = ShareholderBriefSerializer(source="shareholder", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()

    class Meta:
        model = ShareholderContribution
        fields = [
            "id", "shareholder", "shareholder_detail", "amount", "date",
            "bank_account", "cash_account", "reference", "notes", "attachment", "proof_url",
            "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def validate(self, data):
        bank_account = data.get("bank_account")
        cash_account = data.get("cash_account")
        if bank_account and cash_account:
            raise serializers.ValidationError("Un seul compte (banque OU caisse) peut etre renseigne.")
        if not bank_account and not cash_account:
            raise serializers.ValidationError("Un compte de tresorerie (banque ou caisse) est requis.")
        if not data.get("attachment"):
            raise serializers.ValidationError(
                {"attachment": "Un justificatif image est obligatoire pour enregistrer un apport."}
            )
        return data

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return ShareholderContributionService.record_contribution(
                shareholder_id=validated_data["shareholder"].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                actor=actor,
                attachment=validated_data["attachment"],
                bank_account_id=bank_account.id if bank_account else None,
                cash_account_id=cash_account.id if cash_account else None,
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
            )
        except ShareholderContributionError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Un apport enregistre ne peut pas etre modifie.")
