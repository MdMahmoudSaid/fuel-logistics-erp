from decimal import Decimal
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.core.models import LossToleranceConfig, Product
from apps.customers.models import Customer
from apps.documents.models import Document
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    PaymentAllocation,
    Shareholder,
    ShareholderLoan,
    ShareholderProfitDistribution,
    ShareholderWithdrawal,
    SupplierPayment,
    TreasuryTransaction,
    TransportDeduction,
    TransportPayment,
    TransporterAdvance,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.sales.models import (
    CustomerOrder,
    Invoice,
    InvoiceCorrection,
    ProductSellingPriceHistory,
    Sale,
)
from apps.suppliers.models import Supplier
from apps.transport.models import Driver, Transporter, Truck
from apps.trips.models import DeliveryControl, Trip, TripStatusHistory


D = Decimal


class Command(BaseCommand):
    help = (
        "Reset and seed a local/test production-like scenario database. "
        "Refuses production-like environments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Required. Deletes scenario/business data before seeding.",
        )

    def handle(self, *args, **options):
        if not options["reset"]:
            raise CommandError(
                "Refus: cette commande supprime des donnees. Relancer avec --reset."
            )

        self._assert_safe_environment()

        with transaction.atomic():
            self._delete_business_data()
            seed = self._seed_minimal_data()
            remaining = self._remaining_business_rows()

        self._print_summary(seed, remaining)
        if remaining:
            raise CommandError(
                "PROBLEME: des donnees metier anciennes restent: "
                + ", ".join(f"{name}={count}" for name, count in remaining.items())
            )

    def _assert_safe_environment(self):
        db = connection.settings_dict
        db_name = str(db.get("NAME") or "").lower()
        db_host = str(db.get("HOST") or "").lower()
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "").lower()

        prod_markers = ("prod", "production", "live", "real")
        safe_markers = ("test", "dev", "local", "staging", "stage")
        local_hosts = {"", "localhost", "127.0.0.1", "::1", "db", "postgres"}

        if any(marker in db_name for marker in prod_markers):
            raise CommandError(
                f"Refus: nom de base dangereux pour un reset: {db.get('NAME')!r}."
            )
        if "prod" in settings_module:
            raise CommandError(
                f"Refus: module settings production detecte: {settings_module!r}."
            )
        if db_host not in local_hosts:
            raise CommandError(
                f"Refus: hote DB non local pour un reset: {db.get('HOST')!r}."
            )
        if not settings.DEBUG and not any(marker in db_name for marker in safe_markers):
            raise CommandError(
                "Refus: environnement non DEBUG et nom de base sans marqueur "
                "test/dev/local/staging."
            )

    def _delete_business_data(self):
        for model in [
            AuditLog,
            PaymentAllocation,
            InvoiceCorrection,
            TreasuryTransaction,
            ShareholderWithdrawal,
            ShareholderLoan,
            ShareholderProfitDistribution,
            CustomerPayment,
            SupplierPayment,
            TransportPayment,
            TransporterAdvance,
            TransportDeduction,
            ExpenseAllocation,
            Expense,
            Invoice,
            Sale,
            DeliveryControl,
            TripStatusHistory,
            Trip,
            ProductSellingPriceHistory,
            CustomerOrder,
            Document,
            CessionLetter,
            SupplierOrder,
            Truck,
            Driver,
            Transporter,
            Supplier,
            Customer,
            BankAccount,
            CashAccount,
            Shareholder,
        ]:
            model.objects.all().delete()

    def _seed_minimal_data(self):
        admin_permissions = {module: Role.ACTIONS for module in Role.MODULES}
        admin_role, _ = Role.objects.update_or_create(
            name=Role.NAME_ADMIN,
            defaults={"permissions": admin_permissions},
        )
        for role_name in [
            Role.NAME_MANAGEMENT,
            Role.NAME_OPERATIONS,
            Role.NAME_FINANCE,
        ]:
            Role.objects.get_or_create(name=role_name, defaults={"permissions": {}})

        admin, _ = User.objects.update_or_create(
            phone="+22200000000",
            defaults={
                "full_name": "Admin/Test QA",
                "email": "qa@example.test",
                "role": admin_role,
                "is_active": True,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin.set_password("1234")
        admin.save(update_fields=["password", "updated_at"])

        product, _ = Product.objects.update_or_create(
            code="gasoil",
            defaults={"name": "Gasoil", "is_active": True},
        )
        LossToleranceConfig(tolerance_litres=D("100.00"), updated_by=admin).save()

        bank = BankAccount.objects.create(
            name="Banque principale",
            bank_name="Banque Test",
            account_number="QA-001",
            opening_balance=D("200000000.00"),
        )
        cash = CashAccount.objects.create(
            name="Caisse principale",
            location="Bureau QA",
            opening_balance=D("5000000.00"),
        )
        supplier = Supplier.objects.create(
            name="Fournisseur Test",
            company_name="Fournisseur Test",
            country="Senegal",
            is_active=True,
        )
        customer = Customer.objects.create(
            name="Client Test",
            company_name="Client Test",
            is_active=True,
        )
        transporter = Transporter.objects.create(
            name="Transporteur Test",
            company_name="Transporteur Test",
            is_active=True,
        )
        truck = Truck.objects.create(
            internal_id="CAMION-TEST",
            tractor_registration="TRACTEUR-TEST",
            tanker_registration="CITERNE-TEST",
            capacity_litres=D("45000.00"),
            ownership_type=Truck.OwnershipType.EXTERNAL,
            owner_transporter=transporter,
            status=Truck.Status.AVAILABLE,
            is_active=True,
        )
        shareholders = [
            Shareholder.objects.create(
                name="Abdou",
                participation_percent=D("10.00"),
                contribution=D("10000000.00"),
                is_active=True,
            ),
            Shareholder.objects.create(
                name="Sidi",
                participation_percent=D("80.00"),
                contribution=D("80000000.00"),
                is_active=True,
            ),
            Shareholder.objects.create(
                name="Yacoub",
                participation_percent=D("10.00"),
                contribution=D("10000000.00"),
                is_active=True,
            ),
        ]

        return {
            "admin": admin,
            "product": product,
            "bank": bank,
            "cash": cash,
            "supplier": supplier,
            "customer": customer,
            "transporter": transporter,
            "truck": truck,
            "shareholders": shareholders,
        }

    def _remaining_business_rows(self):
        counts = {
            "trips": Trip.objects.count(),
            "delivery_controls": DeliveryControl.objects.count(),
            "invoices": Invoice.objects.count(),
            "sales": Sale.objects.count(),
            "customer_payments": CustomerPayment.objects.count(),
            "supplier_payments": SupplierPayment.objects.count(),
            "transport_payments": TransportPayment.objects.count(),
            "transport_deductions": TransportDeduction.objects.count(),
            "supplier_orders": SupplierOrder.objects.count(),
            "cession_letters": CessionLetter.objects.count(),
            "customer_orders": CustomerOrder.objects.count(),
            "treasury_transactions": TreasuryTransaction.objects.count(),
            "shareholder_distributions": ShareholderProfitDistribution.objects.count(),
            "shareholder_withdrawals": ShareholderWithdrawal.objects.count(),
            "shareholder_loans": ShareholderLoan.objects.count(),
            "audit_logs": AuditLog.objects.count(),
        }
        return {name: count for name, count in counts.items() if count}

    def _print_summary(self, seed, remaining):
        bank = seed["bank"]
        cash = seed["cash"]
        treasury_total = bank.current_balance + cash.current_balance

        self.stdout.write("=== Seed production-like scenario ===")
        self.stdout.write(f"Base verifiee: {connection.settings_dict.get('NAME')}")
        self.stdout.write(f"Admin/Test QA: {seed['admin'].phone}")
        self.stdout.write(f"Produit: {seed['product'].name} ({seed['product'].code})")
        self.stdout.write(f"Banque initiale: {bank.current_balance} XOF")
        self.stdout.write(f"Caisse initiale: {cash.current_balance} XOF")
        self.stdout.write(f"Total tresorerie: {treasury_total} XOF")
        self.stdout.write("Actionnaires crees:")
        for shareholder in seed["shareholders"]:
            self.stdout.write(
                f"- {shareholder.name}: {shareholder.participation_percent}% / "
                f"{shareholder.contribution} XOF"
            )
        self.stdout.write(f"Fournisseur cree: {seed['supplier'].name}")
        self.stdout.write(f"Client cree: {seed['customer'].name}")
        self.stdout.write(f"Transporteur cree: {seed['transporter'].name}")
        self.stdout.write(f"Camion cree: {seed['truck'].internal_id}")
        if remaining:
            self.stdout.write(
                "Confirmation: donnees metier restantes: "
                + ", ".join(f"{name}={count}" for name, count in remaining.items())
            )
        else:
            self.stdout.write(
                "Confirmation: aucune donnee metier ancienne ne reste"
            )
