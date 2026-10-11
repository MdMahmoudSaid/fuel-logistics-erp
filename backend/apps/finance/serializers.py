import json
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils.text import slugify
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.customers.serializers import CustomerBriefSerializer
from apps.documents.models import Document
from apps.documents.validators import validate_image_upload
from apps.finance.labels import describe_treasury_transaction
from apps.suppliers.serializers import SupplierBriefSerializer
from apps.transport.serializers import TransporterBriefSerializer
from apps.trips.models import Trip

from .models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    ExpenseCategory,
    OpeningDebt,
    PaymentAllocation,
    Shareholder,
    ShareholderContribution,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderProfitPeriod,
    ShareholderProfitShare,
    ShareholderWithdrawal,
    ShareholderWithdrawalAllocation,
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
    OpeningDebtError,
    OpeningDebtService,
    PaymentAllocationService,
    ShareholderContributionError,
    ShareholderContributionService,
    ShareholderDistributionError,
    ShareholderDistributionService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderParticipationError,
    ShareholderProfitPreviewService,
    ShareholderProfitPeriodError,
    ShareholderProfitPeriodService,
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


def _account_name(obj) -> str | None:
    """Name of the bank/cash account a payment or advance went through."""
    account = obj.bank_account if obj.bank_account_id else obj.cash_account
    return account.name if account else None


class OpeningDebtSerializer(serializers.ModelSerializer):
    """"Nouvelle dette" (2026-10-11). Create sends exactly one of customer/
    supplier/transporter; paid/remaining/status are always derived."""

    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    party_type = serializers.SerializerMethodField()

    class Meta:
        model = OpeningDebt
        fields = [
            "id", "customer", "supplier", "transporter", "party_type", "amount", "date",
            "reference", "notes", "attachment", "proof_url", "paid_amount", "remaining_amount",
            "status", "cancelled_at", "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "cancelled_at", "recorded_by", "created_at", "updated_at"]

    def get_proof_url(self, obj) -> str | None:
        if not obj.document_id or not obj.document.file:
            return None
        return obj.document.file.url

    def get_paid_amount(self, obj) -> str:
        return f"{OpeningDebtService.describe(obj)['paid_amount']:.2f}"

    def get_remaining_amount(self, obj) -> str:
        return f"{OpeningDebtService.describe(obj)['remaining_amount']:.2f}"

    def get_status(self, obj) -> str:
        return OpeningDebtService.describe(obj)["status"]

    def get_party_type(self, obj) -> str:
        return OpeningDebtService.party_type(obj)

    def validate_attachment(self, value):
        if value is None:
            return value
        return validate_image_upload(value)

    def validate(self, data):
        if self.instance is not None:
            raise serializers.ValidationError(
                "Une dette enregistree ne se modifie pas : annulez-la puis saisissez-la de nouveau."
            )
        parties = [field for field in OpeningDebtService.PARTY_TYPES if data.get(field)]
        if len(parties) != 1:
            raise serializers.ValidationError("Choisissez un seul client, fournisseur ou transporteur.")
        data["party_type"] = parties[0]
        return data

    def create(self, validated_data):
        party_type = validated_data["party_type"]
        try:
            return OpeningDebtService.create(
                party_type=party_type,
                party_id=validated_data[party_type].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                reference=validated_data.get("reference", ""),
                notes=validated_data.get("notes", ""),
                attachment=validated_data.get("attachment"),
                actor=self.context["request"].user,
            )
        except OpeningDebtError as exc:
            raise serializers.ValidationError(str(exc))


class PaymentAllocationSerializer(serializers.ModelSerializer):
    """Read-only nested representation - rows are only ever written by
    PaymentAllocationService.allocate_payment() (guide Section 8.4)."""

    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True, default=None)

    class Meta:
        model = PaymentAllocation
        fields = ["id", "payment", "invoice", "invoice_number", "opening_debt", "amount", "created_at"]
        read_only_fields = fields


class InvoiceAllocationInputSerializer(serializers.Serializer):
    """One line of the `allocations` list accepted by CustomerPaymentSerializer
    on create/update - not itself a ModelSerializer, since the row it
    describes is created by PaymentAllocationService, not by DRF directly
    (docs/PHASE_5_PLAN.md Etape 6/7)."""

    invoice = serializers.IntegerField(required=False, allow_null=True, default=None)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))


class ExistingCreditAllocationInputSerializer(serializers.Serializer):
    """One invoice line for applying an already-recorded customer receipt."""

    invoice = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))


class ExistingCreditAllocationRequestSerializer(serializers.Serializer):
    allocations = ExistingCreditAllocationInputSerializer(many=True, allow_empty=False)


class CustomerPaymentSerializer(serializers.ModelSerializer):
    """docs/PHASE_5_PLAN.md Etape 7.

    `allocations` is write-only input (a plain list of {invoice, amount})
    consumed by PaymentAllocationService.allocate_payment() in create()/
    update() - the actual PaymentAllocation rows it produces are exposed
    back out read-only as `allocations_detail`, so one request can both
    record the payment and immediately imbue/split it across invoices
    (guide Section 8.2: "avec liste d'allocations imbriquee").
    """

    customer_detail = CustomerBriefSerializer(source="customer", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    allocations_detail = PaymentAllocationSerializer(source="allocations", many=True, read_only=True)
    allocations = InvoiceAllocationInputSerializer(many=True, write_only=True, required=False)
    unallocated_amount = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()
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
            "bank_account", "cash_account", "account_name", "reference", "is_indirect", "destination",
            "is_advance", "note", "recorded_by", "recorded_by_detail",
            "allocations", "allocations_detail", "proof", "proof_url",
            "unallocated_amount", "is_reversed",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "recorded_by", "unallocated_amount", "is_reversed", "created_at", "updated_at"]

    def get_unallocated_amount(self, obj) -> str:
        return f"{PaymentAllocationService.get_payment_unallocated_amount(obj):.2f}"

    def get_account_name(self, obj) -> str | None:
        return _account_name(obj)

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

        # Bug fix (2026-09-06): a direct (non-indirect) CustomerPayment
        # posts exactly one TreasuryTransaction at creation time
        # (FinancePostingService.record_customer_payment_treasury, called
        # only from create() below) with amount/date/reference/account
        # frozen from the payment's values at that instant - _post_treasury
        # is idempotent and never re-posts on a later save. Before this
        # fix, update() silently let any of those fields change without
        # ever touching the TreasuryTransaction it had already created, so
        # the bank/cash ledger could permanently disagree with the payment
        # record with nothing in the UI to reveal it. Rather than build a
        # reversal-and-repost flow for a plain PATCH (the same "block
        # first, design a real correction flow later" call already made
        # for SupplierPayment - see SupplierPaymentSerializer.update()
        # above), every field that feeds that TreasuryTransaction is
        # blocked from editing once the payment exists. `allocations`
        # (re-splitting the payment across invoices), `note` and `proof`
        # remain freely editable - none of them are read by
        # record_customer_payment_treasury, so editing them can never
        # desync the treasury.
        if self.instance is not None:
            treasury_fields = ("amount", "payment_date", "customer", "reference")
            changed_treasury_fields = [
                field
                for field in treasury_fields
                if field in data and data[field] != getattr(self.instance, field)
            ]
            # is_indirect/bank_account/cash_account/destination are always
            # present in `data` by this point (resolved above, even on a
            # partial update that never mentioned them) - falling back to
            # the instance's own current value when the caller didn't send
            # one, so this only flags an actual attempted change.
            if data["is_indirect"] != self.instance.is_indirect:
                changed_treasury_fields.append("destination")
            if data["bank_account"] != self.instance.bank_account:
                changed_treasury_fields.append("bank_account")
            if data["cash_account"] != self.instance.cash_account:
                changed_treasury_fields.append("cash_account")
            if changed_treasury_fields:
                raise serializers.ValidationError(
                    {
                        field: (
                            "Un paiement client déjà enregistré ne peut pas être "
                            "modifié sur ce champ : la trésorerie a déjà été "
                            "mise à jour avec la valeur d'origine. Annulez et "
                            "recréez le paiement si une correction est nécessaire."
                        )
                        for field in changed_treasury_fields
                    }
                )

        return data

    def create(self, validated_data):
        allocations = validated_data.pop("allocations", [])
        proof = validated_data.pop("proof", None)
        with transaction.atomic():
            payment = CustomerPayment.objects.create(**validated_data)
            document = None
            if proof:
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
            PaymentAllocationService.apply_customer_credit_to_open_invoices(payment.customer)
        payment.refresh_from_db()
        return payment

    def update(self, instance, validated_data):
        # Only allocations/note/proof can reach here for an existing
        # payment - validate() above already rejected any attempt to
        # change a field that feeds the already-posted TreasuryTransaction.
        allocations = validated_data.pop("allocations", [])
        validated_data.pop("proof", None)
        payment = super().update(instance, validated_data)
        if allocations:
            PaymentAllocationService.allocate_payment(payment.id, allocations)
        PaymentAllocationService.apply_customer_credit_to_open_invoices(payment.customer)
        payment.refresh_from_db()
        return payment


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierBriefSerializer(source="supplier", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    proof_url = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPayment
        fields = [
            "id", "supplier", "supplier_detail", "supplier_order", "opening_debt", "amount", "payment_date",
            "method", "bank_account", "cash_account", "is_advance", "reference",
            "recorded_by", "recorded_by_detail", "proof_url", "is_reversed",
            "created_at", "updated_at",
        ]
        # is_reversed is read-only here: only SupplierPaymentCancellationService.
        # cancel_supplier_payment (via the /cancel/ action) may ever set it -
        # never a plain PATCH, which would skip the treasury reversal.
        read_only_fields = ["id", "opening_debt", "recorded_by", "is_reversed", "created_at", "updated_at"]

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
    supplier_detail = SupplierBriefSerializer(source="supplier", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    account_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierAdvance
        fields = [
            "id", "supplier", "supplier_detail", "bank_account", "cash_account",
            "amount", "date", "reference", "notes", "attachment", "proof_url",
            "remaining_amount", "account_name", "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "remaining_amount", "recorded_by", "created_at", "updated_at"]

    def get_account_name(self, obj) -> str | None:
        return _account_name(obj)

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
    transporter_detail = TransporterBriefSerializer(source="transporter", read_only=True)
    attachment = serializers.FileField(write_only=True, required=False, allow_null=True, default=None)
    proof_url = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    account_name = serializers.SerializerMethodField()

    class Meta:
        model = TransporterAdvance
        fields = [
            "id", "transporter", "transporter_detail", "bank_account", "cash_account",
            "amount", "date", "reference", "notes", "attachment", "proof_url",
            "remaining_amount", "settled", "account_name", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "remaining_amount", "settled", "created_at", "updated_at"]

    def get_account_name(self, obj) -> str | None:
        return _account_name(obj)

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
    can_modify = serializers.SerializerMethodField()

    def get_can_modify(self, obj):
        from .commission import can_modify_commission

        return can_modify_commission(obj)

    transporter_detail = TransporterBriefSerializer(source="transporter", read_only=True)
    trip_reference = serializers.CharField(source="trip.reference", read_only=True)
    net_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    deduction_label = serializers.SerializerMethodField()

    class Meta:
        model = TransportPayment
        fields = [
            "id", "trip", "trip_reference", "transporter", "transporter_detail",
            "calculation_method", "base_amount", "unit_price_per_litre", "deduction_amount",
            "deduction_label", "advance_applied", "net_amount", "status", "created_at", "updated_at", "can_modify",
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

        # Bug found by chance (client feedback 2026-09-10): nothing stopped
        # a second TransportPayment from being created for a trip that
        # already has one (the "Ajouter des frais de transport" button on
        # TripDetail.vue had no guard either) - two settlements piled up
        # for the same trip, and the deduction-sync loop
        # (_sync_transport_payment_deductions) then applied the exact same
        # deduction to both, doubling what looked owed/owed-back. A trip
        # has exactly one settlement, same invariant as its Sale
        # (OneToOneField) - only on create (self.instance is None): a PATCH
        # to an existing payment must still go through untouched.
        if self.instance is None and trip is not None:
            if TransportPayment.objects.filter(trip=trip).exists():
                raise serializers.ValidationError(
                    f"Le trajet {trip.reference} a deja un reglement transport "
                    "enregistre ; un trajet ne peut en avoir qu'un seul."
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
            if unit_price_per_litre <= 0:
                raise serializers.ValidationError(
                    {"unit_price_per_litre": "Le prix par litre doit etre superieur a zero."}
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

        if data.get("base_amount", Decimal("0")) < 0:
            raise serializers.ValidationError({"base_amount": "Le montant ne peut pas etre negatif."})

        return data

    def get_deduction_label(self, obj) -> str:
        # Latest deduction, picked from `.all()` so the deductions
        # TransportPaymentViewSet prefetches for a page are reused.
        deduction = max(
            obj.trip.transport_deductions.all(),
            key=lambda item: (item.created_at, item.id),
            default=None,
        )
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
    # Who/what paid this expense (client request 2026-09-25): a customer (paid
    # on the company's behalf), a bank account or a cash account; None while
    # unpaid.
    paid_via = serializers.SerializerMethodField()
    paid_via_name = serializers.SerializerMethodField()
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
            "paid_by_customer_directly", "paid_via", "paid_via_name", "notes",
            "allocations", "allocations_detail", "bank_account", "cash_account",
            "created_at", "updated_at",
        ]
        # paid_by_customer_directly/status=PAID for the indirect case is only
        # ever set by IndirectSettlementService, never a direct client write.
        read_only_fields = [
            "id", "paid_by_customer_directly", "paid_via", "paid_via_name",
            "created_at", "updated_at",
        ]

    def _payer(self, obj) -> tuple[str | None, str | None]:
        cached = getattr(obj, "_payer_cache", None)
        if cached is not None:
            return cached
        result: tuple[str | None, str | None] = (None, None)
        if obj.status in (Expense.Status.PAID, Expense.Status.PARTIALLY_PAID):
            if obj.paid_by_customer_directly:
                payment = obj.indirect_settlement_payment
                result = ("customer", payment.customer.name if payment else None)
            else:
                transaction_row = (
                    TreasuryTransaction.objects.filter(
                        source_content_type=ContentType.objects.get_for_model(Expense),
                        source_object_id=obj.pk,
                        type=TreasuryTransaction.Type.MONEY_OUT,
                    )
                    .select_related("bank_account", "cash_account")
                    .order_by("id")
                    .first()
                )
                if transaction_row is not None:
                    if transaction_row.bank_account_id:
                        result = ("bank", transaction_row.bank_account.name)
                    elif transaction_row.cash_account_id:
                        result = ("cash", transaction_row.cash_account.name)
        obj._payer_cache = result
        return result

    def get_paid_via(self, obj) -> str | None:
        return self._payer(obj)[0]

    def get_paid_via_name(self, obj) -> str | None:
        return self._payer(obj)[1]

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
        # Bug fix (2026-09-03 recette manuelle): "allocations" in
        # validated_data (checked before popping) distinguishes "the
        # client sent a new allocation list, replace it" from "allocations
        # wasn't touched in this PATCH, leave the existing rows alone" -
        # popping first and defaulting to [] made every edit that included
        # allocations *append* a duplicate ExpenseAllocation row instead of
        # overwriting the existing one, doubling the trip's allocated
        # amount. Only reachable for an UNPAID expense in practice -
        # validate() already blocks touching "allocations" once
        # PAID/PARTIALLY_PAID.
        replace_allocations = "allocations" in validated_data
        allocations = validated_data.pop("allocations", [])
        expense = super().update(instance, validated_data)
        if replace_allocations:
            expense.allocations.all().delete()
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
    # A CharField validated against ExpenseCategory (like ExpenseSerializer),
    # not the built-in enum: user-created categories must work too.
    category = serializers.CharField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
    calculation_method = serializers.ChoiceField(
        choices=Expense.CalculationMethod.choices, default=Expense.CalculationMethod.MANUAL
    )
    date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_category(self, value):
        if not ExpenseCategory.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("Categorie de depense invalide ou inactive.")
        return value


class CustomerPaidExpensesRequestSerializer(serializers.Serializer):
    """Input for POST /api/expenses/record-customer-paid/ - one general
    expense paid by one or several customers (each `payers[].amount` comes
    off what that customer owes, or becomes a company debt to him)."""

    class PayerSerializer(serializers.Serializer):
        customer = serializers.IntegerField()
        amount = serializers.DecimalField(
            max_digits=16, decimal_places=2, min_value=Decimal("0.01")
        )

    category = serializers.CharField()
    date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    payers = PayerSerializer(many=True, allow_empty=False)

    def validate_category(self, value):
        if not ExpenseCategory.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("Categorie de depense invalide ou inactive.")
        return value


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
    # Overpayment -> advance (2026-10-09): sent only after the user
    # confirmed the surplus popup; see ControlledDebtPaymentService.record_payment.
    surplus_as_advance = serializers.BooleanField(required=False, default=False)
    amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=Decimal("0.01")
    )
    date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    attachment = serializers.FileField(required=False, allow_null=True, default=None)

    def validate_attachment(self, value):
        if value is None:
            return value
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
        # `contribution` is read-only through this API (bug fix, 2026-09-10:
        # the Associes "Ajouter/Modifier" form exposed it as an ordinary
        # writable field with no linked bank/cash account, so a user could
        # enter any amount there and it would silently reduce
        # distributable_result via ShareholderContributionService
        # .get_total_capital() with no corresponding money ever entering
        # treasury. It's now a historical/bootstrap-only figure set through
        # the backend (seed data, admin, or a data migration) - normal
        # capital contributions must go through ShareholderContribution /
        # "Nouvel apport en capital", which requires a real account.
        read_only_fields = ["id", "contribution", "created_at", "updated_at"]

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
    dedicated `validate`/`cancel` actions, never a plain PATCH.
    """

    created_by_detail = UserSerializer(source="created_by", read_only=True)
    validated_by_detail = UserSerializer(source="validated_by", read_only=True)
    cancelled_by_detail = UserSerializer(source="cancelled_by", read_only=True)
    shares = ShareholderProfitShareSerializer(many=True, read_only=True)
    # DRAFT only: the profit still left to distribute, i.e. what validation
    # will compare total_profit against, so the UI can disable "Valider"
    # with the same figure the backend guard uses.
    available_to_distribute = serializers.SerializerMethodField()

    def get_available_to_distribute(self, obj) -> str | None:
        if obj.status != ShareholderProfitDistribution.Status.DRAFT:
            return None
        preview = ShareholderProfitPreviewService.get_preview()
        return f"{preview['distributable_result']:.2f}"

    class Meta:
        model = ShareholderProfitDistribution
        fields = [
            "id", "period_start", "period_end", "total_profit", "status",
            "available_to_distribute",
            "created_by", "created_by_detail", "validated_by", "validated_by_detail",
            "validated_at", "cancelled_by", "cancelled_by_detail", "cancelled_at",
            "shares", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "available_to_distribute", "created_by", "validated_by",
            "validated_at", "cancelled_by", "cancelled_at", "created_at", "updated_at",
        ]

    def create(self, validated_data):
        actor = self.context["request"].user
        try:
            return ShareholderDistributionService.create_distribution(
                period_start=validated_data["period_start"],
                period_end=validated_data["period_end"],
                total_profit=validated_data["total_profit"],
                actor=actor,
            )
        except ShareholderDistributionError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Une distribution ne peut pas etre modifiee ; utilisez l'action 'valider' ou 'annuler'."
        )


class ShareholderProfitPeriodSerializer(serializers.ModelSerializer):
    opened_by_detail = UserSerializer(source="opened_by", read_only=True)
    closed_by_detail = UserSerializer(source="closed_by", read_only=True)
    reopened_by_detail = UserSerializer(source="reopened_by", read_only=True)
    distribution_detail = ShareholderProfitDistributionSerializer(
        source="distribution", read_only=True
    )
    live_net_profit = serializers.SerializerMethodField()
    preview_end_date = serializers.SerializerMethodField()

    def get_live_net_profit(self, obj):
        if obj.status != ShareholderProfitPeriod.Status.OPEN:
            return None
        preview = ShareholderProfitPreviewService.get_preview(
            date_from=obj.start_date, date_to=timezone.localdate()
        )
        return f"{preview['net_profit']:.2f}"

    def get_preview_end_date(self, obj):
        return str(timezone.localdate()) if obj.status == ShareholderProfitPeriod.Status.OPEN else None

    class Meta:
        model = ShareholderProfitPeriod
        fields = [
            "id", "start_date", "end_date", "status", "net_profit", "live_net_profit",
            "preview_end_date", "distribution", "distribution_detail", "opened_by",
            "opened_by_detail", "closed_by", "closed_by_detail", "closed_at",
            "reopened_by", "reopened_by_detail", "reopened_at", "reopen_reason",
            "reopen_count", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "end_date", "status", "net_profit", "live_net_profit",
            "preview_end_date", "distribution", "opened_by", "closed_by", "closed_at",
            "reopened_by", "reopened_at", "reopen_reason", "reopen_count", "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        try:
            return ShareholderProfitPeriodService.open_period(
                validated_data["start_date"], self.context["request"].user
            )
        except ShareholderProfitPeriodError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Utilisez les actions cloturer ou rouvrir pour modifier une periode."
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


class ShareholderWithdrawalAllocationSerializer(serializers.ModelSerializer):
    """Read-only - rows are only ever created by
    ShareholderWithdrawalService.record_withdrawal()'s automatic
    allocation (design doc 2026-09-15-capital-associe-retrait-design.md)."""

    class Meta:
        model = ShareholderWithdrawalAllocation
        fields = ["profit_share", "contribution", "amount"]


class ShareholderWithdrawalSerializer(serializers.ModelSerializer):
    shareholder_detail = ShareholderBriefSerializer(source="shareholder", read_only=True)
    recorded_by_detail = UserSerializer(source="recorded_by", read_only=True)
    allocations = ShareholderWithdrawalAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = ShareholderWithdrawal
        fields = [
            "id", "shareholder", "shareholder_detail", "allocations", "amount", "date",
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
        return data

    def create(self, validated_data):
        actor = self.context["request"].user
        bank_account = validated_data.get("bank_account")
        cash_account = validated_data.get("cash_account")
        try:
            return ShareholderWithdrawalService.record_withdrawal(
                shareholder_id=validated_data["shareholder"].id,
                amount=validated_data["amount"],
                date=validated_data["date"],
                actor=actor,
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
    remaining_capital = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = ShareholderContribution
        fields = [
            "id", "shareholder", "shareholder_detail", "amount", "amount_returned",
            "remaining_capital", "date",
            "bank_account", "cash_account", "reference", "notes", "attachment", "proof_url",
            "recorded_by", "recorded_by_detail", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "amount_returned", "remaining_capital", "recorded_by", "created_at", "updated_at"]

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
