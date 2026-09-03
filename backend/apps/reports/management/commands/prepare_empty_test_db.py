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
    ExpenseCategory,
    PaymentAllocation,
    Shareholder,
    ShareholderContribution,
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


class Command(BaseCommand):
    help = (
        "Prepare a local/test database with all domain/business counters at zero. "
        "Refuses production-like environments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Required. Deletes local/test data from the selected database.",
        )
        parser.add_argument(
            "--with-admin",
            action="store_true",
            help="Create a login admin (+22200000000 / PIN 1234) after reset.",
        )

    def handle(self, *args, **options):
        if not options["reset"]:
            raise CommandError(
                "Refus: cette commande supprime des donnees. Relancer avec --reset."
            )

        self._assert_safe_environment()

        with transaction.atomic():
            self._delete_all_test_data()
            self._reseed_required_system_rows()
            admin = self._create_admin() if options["with_admin"] else None
            counts = self._domain_counts()

        # Bug fix (2026-09-03 recette manuelle): expense_categories and
        # transporters are never truly zero after this reset anymore -
        # _reseed_required_system_rows() recreates the is_system=True
        # ExpenseCategory rows (customs/transit/road_transit/road/loading/
        # transport - hardcoded elsewhere by code string, e.g.
        # ControlledDebtPaymentService, and impossible to recreate through
        # the UI, which only lets a user create non-system categories) and
        # the single is_internal=True Transporter ("Flotte propre /
        # Interne" - Truck.save() requires it for every COMPANY_OWNED
        # truck and there is no UI path to mark a transporter internal
        # either). Both are always-ignored counts now, same treatment as
        # "users" when --with-admin recreates one.
        ignored_counts = {"expense_categories", "transporters"} | (
            {"users"} if admin else set()
        )
        remaining = {
            name: count
            for name, count in counts.items()
            if count and name not in ignored_counts
        }
        if remaining:
            raise CommandError(
                "PROBLEME: des donnees restent apres reset: "
                + ", ".join(f"{name}={count}" for name, count in remaining.items())
            )

        self.stdout.write("=== Base vide prete ===")
        self.stdout.write(f"Base verifiee: {connection.settings_dict.get('NAME')}")
        self.stdout.write("Donnees metier: 0")
        self.stdout.write(
            f"Categories systeme recreees: {ExpenseCategory.objects.filter(is_system=True).count()}"
        )
        self.stdout.write(
            "Transporteur interne recree: "
            + (Transporter.objects.get(is_internal=True).name)
        )
        self.stdout.write(f"Utilisateurs: {User.objects.count()}")
        if admin:
            self.stdout.write(f"Admin cree: {admin.phone} / PIN 1234")

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

    def _delete_all_test_data(self):
        for model in [
            AuditLog,
            PaymentAllocation,
            InvoiceCorrection,
            TreasuryTransaction,
            ShareholderWithdrawal,
            # Must precede Shareholder/BankAccount/CashAccount/User below -
            # shareholder/bank_account/cash_account/recorded_by are all
            # on_delete=PROTECT.
            ShareholderContribution,
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
            LossToleranceConfig,
            # No FK ever points at ExpenseCategory (Expense.category is a
            # plain code string) - safe to delete at any point, including
            # is_system=True rows (same "reset to true zero" treatment as
            # the seeded Product rows below).
            ExpenseCategory,
            Product,
            User,
        ]:
            model.objects.all().delete()

    def _reseed_required_system_rows(self):
        # Bug fix (2026-09-03 recette manuelle): mirrors the exact seed
        # data of finance/migrations/0014_expensecategory.py and
        # transport/migrations/0004_truck_owner_transporter_mandatory.py -
        # RunPython data migrations only ever run once (on first apply),
        # never again just because the rows they created were later
        # deleted, so this reset must recreate them itself.
        system_categories = [
            ("customs", "Customs", 0),
            ("transit", "Transit", 2),
            ("road_transit", "Road transit", 3),
            ("transport", "Transport", 4),
            ("loading", "Loading", 5),
            ("road", "Road", 7),
        ]
        for code, name, display_order in system_categories:
            ExpenseCategory.objects.create(
                code=code, name=name, is_system=True, display_order=display_order
            )
        Transporter.objects.create(name="Flotte propre / Interne", is_internal=True)

    def _create_admin(self):
        admin_permissions = {module: Role.ACTIONS for module in Role.MODULES}
        admin_role, _ = Role.objects.update_or_create(
            name=Role.NAME_ADMIN,
            defaults={"permissions": admin_permissions},
        )
        admin = User.objects.create_superuser(
            phone="+22200000000",
            pin="1234",
            full_name="Admin/Test Vide",
            email="admin-empty@example.test",
            role=admin_role,
        )
        return admin

    def _domain_counts(self):
        return {
            "users": User.objects.count(),
            "products": Product.objects.count(),
            "expense_categories": ExpenseCategory.objects.count(),
            "loss_tolerance_configs": LossToleranceConfig.objects.count(),
            "suppliers": Supplier.objects.count(),
            "customers": Customer.objects.count(),
            "transporters": Transporter.objects.count(),
            "drivers": Driver.objects.count(),
            "trucks": Truck.objects.count(),
            "bank_accounts": BankAccount.objects.count(),
            "cash_accounts": CashAccount.objects.count(),
            "shareholders": Shareholder.objects.count(),
            "shareholder_contributions": ShareholderContribution.objects.count(),
            "supplier_orders": SupplierOrder.objects.count(),
            "cession_letters": CessionLetter.objects.count(),
            "customer_orders": CustomerOrder.objects.count(),
            "trips": Trip.objects.count(),
            "delivery_controls": DeliveryControl.objects.count(),
            "sales": Sale.objects.count(),
            "invoices": Invoice.objects.count(),
            "customer_payments": CustomerPayment.objects.count(),
            "supplier_payments": SupplierPayment.objects.count(),
            "transport_payments": TransportPayment.objects.count(),
            "transport_deductions": TransportDeduction.objects.count(),
            "transporter_advances": TransporterAdvance.objects.count(),
            "expenses": Expense.objects.count(),
            "treasury_transactions": TreasuryTransaction.objects.count(),
            "documents": Document.objects.count(),
            "audit_logs": AuditLog.objects.count(),
            "shareholder_distributions": ShareholderProfitDistribution.objects.count(),
            "shareholder_withdrawals": ShareholderWithdrawal.objects.count(),
            "shareholder_loans": ShareholderLoan.objects.count(),
        }
