from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import Role, User
from apps.core.models import Product
from apps.customers.models import Customer
from apps.finance.models import (
    BankAccount,
    CashAccount,
    CustomerPayment,
    Expense,
    ExpenseAllocation,
    Shareholder,
    ShareholderLoan,
    ShareholderProfitShare,
    TreasuryTransaction,
    TransportDeduction,
    TransportPayment,
)
from apps.finance.serializers import CustomerPaymentSerializer
from apps.finance.services import (
    ControlledDebtPaymentError,
    ControlledDebtPaymentService,
    PaymentAllocationService,
    ShareholderDistributionService,
    ShareholderLedgerService,
    ShareholderLoanError,
    ShareholderLoanService,
    ShareholderWithdrawalError,
    ShareholderWithdrawalService,
)
from apps.purchasing.models import CessionLetter, SupplierOrder
from apps.purchasing.services import SupplierStockService
from apps.reports.queries.customer_statement import CustomerStatementQuery
from apps.reports.queries.shareholder_statement import ShareholderStatementQuery
from apps.reports.queries.supplier_statement import SupplierStatementQuery
from apps.reports.queries.transporter_statement import TransporterStatementQuery
from apps.reports.queries.treasury_statement import TreasuryStatementQuery
from apps.reports.services.profit import TripProfitService
from apps.reports.services.stock import TheoreticalStockService
from apps.sales.models import Invoice
from apps.sales.services import InvoiceService
from apps.suppliers.models import Supplier
from apps.transport.models import Driver, Transporter, Truck
from apps.trips.models import DeliveryControl, Trip, TripStatusHistory
from apps.trips.services import (
    DeliveryService,
    InvalidTripTransition,
    SaleBelowCostConfirmationRequired,
    TripCostService,
    TripWorkflowService,
)

D = Decimal
TODAY = date(2026, 8, 28)


class DummyRequest:
    def __init__(self, user):
        self.user = user


class ScenarioReport:
    def __init__(self):
        self.rows = []
        self.problems = []

    def check(self, section, label, formula, expected, actual):
        expected = self._normalize(expected)
        actual = self._normalize(actual)
        ok = actual == expected
        self.rows.append(
            {
                "section": section,
                "label": label,
                "formula": formula,
                "expected": expected,
                "actual": actual,
                "diff": self._diff(expected, actual),
                "status": "OK" if ok else "PROBLEME",
            }
        )
        if not ok:
            self.problems.append(self.rows[-1])
        return ok

    def note(self, section, label, actual, ok=True):
        self.rows.append(
            {
                "section": section,
                "label": label,
                "formula": "-",
                "expected": "voir scenario",
                "actual": actual,
                "diff": "-",
                "status": "OK" if ok else "PROBLEME",
            }
        )
        if not ok:
            self.problems.append(self.rows[-1])

    def print(self):
        sections = []
        for row in self.rows:
            if row["section"] not in sections:
                sections.append(row["section"])
        print("\n\n=== RAPPORT SCENARIO COMPLET PRODUCTION-LIKE ===")
        print("Base: pytest/Django test database creee par le runner; aucune base reelle videe.")
        print("Sauvegarde: non applicable, base de test ephemere propre; donnees dev/prod non touchees.")
        for section in sections:
            print(f"\n## {section}")
            for row in [item for item in self.rows if item["section"] == section]:
                print(
                    f"- {row['status']} | {row['label']} | formule={row['formula']} | "
                    f"attendu={row['expected']} | reel={row['actual']} | diff={row['diff']}"
                )
        print("\n## Bugs trouves")
        if not self.problems:
            print("- Aucun ecart chiffre detecte par ce harnais.")
        for row in self.problems:
            print(
                f"- {row['section']} / {row['label']}: attendu {row['expected']}, "
                f"reel {row['actual']}, diff {row['diff']}"
            )
        print("\n## Corrections recommandees")
        if any(row["label"] == "benefice trajet" for row in self.problems):
            print(
                "- Aligner TripProfitService avec la regle confirmee: facture client "
                "+ indemnisation perte transporteur - cout total reel du trajet charge."
            )
        if any(row["label"] == "libelle deduction transporteur" for row in self.problems):
            print(
                "- Harmoniser le libelle de deduction avec le libelle metier attendu: "
                "'Manque quantite - TRIP-TEST-PERTE - 50 L x 900 XOF/L'."
            )
        if not self.problems:
            print("- Conserver ce scenario comme test de regression automatise.")

    @staticmethod
    def _normalize(value):
        if isinstance(value, Decimal):
            return value.quantize(D("0.01"))
        return value

    @staticmethod
    def _diff(expected, actual):
        if isinstance(expected, Decimal) and isinstance(actual, Decimal):
            return (actual - expected).quantize(D("0.01"))
        return "-" if expected == actual else "different"


def money(value):
    return D(str(value)).quantize(D("0.01"))


def post_customer_payment(*, customer, amount, bank, invoice, user, reference):
    proof = SimpleUploadedFile(
        f"{reference}.jpg",
        b"scenario proof image",
        content_type="image/jpeg",
    )
    serializer = CustomerPaymentSerializer(
        data={
            "customer": customer.id,
            "amount": str(amount),
            "payment_date": TODAY.isoformat(),
            "method": CustomerPayment.Method.BANK_TRANSFER,
            "destination": CustomerPayment.Destination.BANK,
            "bank_account": bank.id,
            "reference": reference,
            "allocations": [{"invoice": invoice.id, "amount": str(amount)}],
            "proof": proof,
        },
        context={"request": DummyRequest(user)},
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save(recorded_by=user)


def create_trip(
    *,
    reference,
    quantity,
    supplier,
    order,
    cession,
    product,
    transporter,
    truck,
    driver,
    user,
    client=None,
):
    return Trip.objects.create(
        reference=reference,
        truck=truck,
        transporter=transporter,
        driver=driver,
        supplier=supplier,
        supplier_order=order,
        cession_letter=cession,
        product=product,
        quantity_loaded=quantity,
        client=client,
        destination_type=Trip.DestinationType.CUSTOMER
        if client
        else Trip.DestinationType.COMPANY_STOCK,
        loading_date=TODAY,
        bl_reference=f"BL-{reference}",
        created_by=user,
    )


def create_trip_expense(*, trip, category, amount):
    expense = Expense.objects.create(
        category=category,
        amount=amount,
        calculation_method=Expense.CalculationMethod.PER_LITRE,
        date=TODAY,
    )
    ExpenseAllocation.objects.create(
        expense=expense,
        content_type=ContentType.objects.get_for_model(Trip),
        object_id=trip.id,
        allocated_amount=amount,
    )
    return expense


def transition_path(trip, statuses, user):
    for status in statuses:
        trip = TripWorkflowService.transition_trip(trip.id, status, user)
    return trip


def sync_shortage(*, trip, received_qty, unit_selling_price):
    with transaction.atomic():
        DeliveryService.sync_transport_shortage_deduction(
            trip=trip,
            received_qty=received_qty,
            unit_selling_price=unit_selling_price,
        )


@pytest.mark.django_db(transaction=True)
def test_scenario_complet_production_like(capsys):
    report = ScenarioReport()

    admin_role, _ = Role.objects.update_or_create(
        name=Role.NAME_ADMIN,
        defaults={"permissions": {module: Role.ACTIONS for module in Role.MODULES}},
    )
    user = User.objects.create_superuser(
        phone="+22200000000",
        pin="1234",
        full_name="Scenario Admin",
        role=admin_role,
    )
    shareholders = {
        "Abdou Mohamed": Shareholder.objects.create(
            name="Abdou Mohamed", participation_percent=D("10.00"), contribution=money(10000000)
        ),
        "Sidi Mohamed": Shareholder.objects.create(
            name="Sidi Mohamed", participation_percent=D("80.00"), contribution=money(80000000)
        ),
        "Yacoub": Shareholder.objects.create(
            name="Yacoub", participation_percent=D("10.00"), contribution=money(10000000)
        ),
    }
    bank = BankAccount.objects.create(name="Banque Test Principale", opening_balance=money(200000000))
    cash = CashAccount.objects.create(name="Caisse Test", opening_balance=money(5000000))
    gasoil, _ = Product.objects.get_or_create(code="gasoil", defaults={"name": "Gasoil"})
    Product.objects.get_or_create(code="essence", defaults={"name": "Essence"})
    supplier = Supplier.objects.create(name="Supplier Test")
    transporter = Transporter.objects.create(name="Transporteur Test")
    customer = Customer.objects.create(name="Client Test")
    driver = Driver.objects.create(name="Chauffeur Test")
    truck = Truck.objects.create(
        internal_id="TRK-TEST-001",
        tractor_registration="TRACT-001",
        tanker_registration="TANK-001",
        capacity_litres=D("60000.00"),
        owner_transporter=transporter,
        default_driver=driver,
    )

    report.check("1. Etat initial", "total pourcentage actionnaires", "10 + 80 + 10", D("100.00"), sum(s.participation_percent for s in shareholders.values()))
    report.check("1. Etat initial", "total contributions", "10M + 80M + 10M", money(100000000), sum(s.contribution for s in shareholders.values()))
    report.check("1. Etat initial", "banques", "solde initial banque", money(200000000), bank.current_balance)
    report.check("1. Etat initial", "caisses", "solde initial caisse", money(5000000), cash.current_balance)
    report.check("1. Etat initial", "total tresorerie", "200M + 5M", money(205000000), bank.current_balance + cash.current_balance)

    order = SupplierOrder.objects.create(
        reference="PO-TEST-001",
        supplier=supplier,
        product=gasoil,
        purchase_date=TODAY,
        quantity_litres=D("100000.00"),
        unit_price=D("500.0000"),
        status=SupplierOrder.Status.CONFIRMED,
        created_by=user,
    )
    supplier_debt = ControlledDebtPaymentService.describe_supplier(supplier)
    report.check("2. Achat fournisseur", "montant achat", "100 000 x 500", money(50000000), order.total_amount)
    # Bug fix (client business rule, confirmed 2026-09-06): a confirmed
    # purchase is a commitment, not yet a debt - the supplier debt must
    # only appear once fuel is actually loaded onto a trip, so it is 0
    # right after confirmation, before any cession or loading exists.
    report.check("2. Achat fournisseur", "dette fournisseur avant tout chargement", "aucun chargement -> 0", money(0), supplier_debt["remaining_amount"])
    report.check("2. Achat fournisseur", "reliquat fournisseur", "100 000 - charge", D("100000.00"), SupplierStockService.get_purchase_reliquat(order))

    cession = CessionLetter.objects.create(
        reference="LC-TEST-001",
        supplier_order=order,
        authorized_quantity=D("45000.00"),
        issue_date=TODAY,
        created_by=user,
    )
    # Bug fix (client business rule, confirmed 2026-09-06): issuing a
    # cession letter alone must not move the reliquat - only an actual
    # loading does (exact client example: achat 200 000 L, cession
    # 200 000 L, chargement 100 000 L -> reliquat = 100 000 L, reproduced
    # here at a different scale further below once this order's second
    # 55 000 L cession/trip is added).
    report.check("3. Lettre de cession", "reliquat inchange par la cession seule", "100 000 (chargement seul compte)", D("100000.00"), SupplierStockService.get_purchase_reliquat(order))
    report.check("3. Lettre de cession", "cession disponible", "45 000 - charge", D("45000.00"), SupplierStockService.get_cession_remaining(cession))

    trip = create_trip(
        reference="TRIP-TEST-PERTE",
        quantity=D("45000.00"),
        supplier=supplier,
        order=order,
        cession=cession,
        product=gasoil,
        transporter=transporter,
        truck=truck,
        driver=driver,
        client=customer,
        user=user,
    )
    report.check("4. Trajet et frais", "trajet cree", "reference creee", "TRIP-TEST-PERTE", trip.reference)
    report.check("4. Trajet et frais", "client trajet", "Client Test", "Client Test", trip.client.name)
    # Bug fix regression (client business rule, confirmed 2026-09-06): now
    # that 45 000 L of the 100 000 L purchased is actually loaded onto this
    # trip, the reliquat drops and a real, partial supplier debt appears -
    # exactly the client's "achat partiel, chargement partiel" example.
    supplier_debt_after_loading = ControlledDebtPaymentService.describe_supplier(supplier)
    report.check("4. Trajet et frais", "reliquat fournisseur apres chargement partiel", "100 000 - 45 000 charges", D("55000.00"), SupplierStockService.get_purchase_reliquat(order))
    report.check("4. Trajet et frais", "dette fournisseur sur quantite chargee", "45 000 x 500", money(22500000), supplier_debt_after_loading["remaining_amount"])

    transport_payment = TransportPayment.objects.create(
        trip=trip,
        transporter=transporter,
        calculation_method=TransportPayment.CalculationMethod.PER_LITRE,
        unit_price_per_litre=D("65.0000"),
        base_amount=money(2925000),
        status=TransportPayment.Status.PAYABLE,
    )
    transit_expense = create_trip_expense(trip=trip, category=Expense.Category.TRANSIT, amount=money(450000))
    customs_expense = create_trip_expense(trip=trip, category=Expense.Category.CUSTOMS, amount=money(10125000))
    cost_basis = TripCostService.calculate_trip_cost_basis(trip)
    report.check("4. Trajet et frais", "commission transporteur", "45 000 x 65", money(2925000), transport_payment.base_amount)
    report.check("4. Trajet et frais", "transit classique", "45 000 x 10", money(450000), transit_expense.amount)
    report.check("4. Trajet et frais", "douane", "45 000 x 225", money(10125000), customs_expense.amount)
    report.check("4. Trajet et frais", "prix revient estime", "(22 500 000 + 2 925 000 + 450 000 + 10 125 000) / 45 000", D("800.00"), cost_basis["unit_cost"].quantize(D("0.01")))

    workflow = [
        Trip.Status.SENT_FOR_LOADING,
        Trip.Status.LOADING,
        Trip.Status.LOADED,
        Trip.Status.ROAD_TRANSIT,
        Trip.Status.IN_TRANSIT,
        Trip.Status.BORDER,
        Trip.Status.CUSTOMS,
        Trip.Status.GOING_TO_CLIENT,
        Trip.Status.ARRIVED_AT_CLIENT,
        # Client correction (2026-09-04 recette): QUANTITY_CONTROL is no
        # longer a mandatory intermediate stop - a trip is delivered
        # directly from ARRIVED_AT_CLIENT (see
        # TripWorkflowService.FORWARD_TRANSITIONS).
    ]
    trip = transition_path(trip, workflow, user)
    history = list(TripStatusHistory.objects.filter(trip=trip).values_list("new_status", flat=True))
    report.check("4. Trajet et frais", "statut transit routiere present", "ROAD_TRANSIT dans workflow", True, Trip.Status.ROAD_TRANSIT in history)
    report.check("4. Trajet et frais", "historique statuts", "9 transitions", 9, len(history))
    report.check("4. Trajet et frais", "statut avant controle", "ARRIVED_AT_CLIENT", Trip.Status.ARRIVED_AT_CLIENT, Trip.objects.get(pk=trip.pk).status)

    control = DeliveryService.record_delivery(
        trip.id,
        received_qty=D("44850.00"),
        control_date=TODAY,
        method=DeliveryControl.Method.MANUAL_GAUGE,
        controller=user,
        unit_selling_price=D("900.0000"),
    )
    trip.refresh_from_db()
    deduction = TransportDeduction.objects.get(trip=trip)
    transport_payment.refresh_from_db()
    deduction_label = (
        f"Manque quantite - {trip.reference} - "
        f"{deduction.chargeable_quantity.quantize(D('1'))} L x {deduction.unit_price.quantize(D('1'))} XOF/L"
    )
    # Recette corrections Task 3 (2026-09-04): 44 850 L recus (150 L de perte,
    # au-dessus de la tolerance de 100 L par defaut - une valeur volontairement
    # eloignee de la frontiere 100 L/100 L pour eviter tout cas limite), seuls
    # les 50 L au-dela de la tolerance sont factures au transporteur
    # (sync_transport_shortage_deduction ne facture plus la totalite du
    # manquant, bug fixe dans ce meme commit).
    report.check("5. Controle quantite et perte", "quantite chargee", "source trajet", D("45000.00"), control.loaded_quantity)
    report.check("5. Controle quantite et perte", "quantite recue", "saisie controle", D("44850.00"), control.received_quantity)
    report.check("5. Controle quantite et perte", "perte", "45 000 - 44 850", D("150.00"), control.loss_quantity)
    report.check("6. Deduction transporteur", "deduction montant", "(150 - 100 tolerance) x 900", money(45000), deduction.amount)
    report.check("6. Deduction transporteur", "deduction liee au trajet", "trip reference", "TRIP-TEST-PERTE", deduction.trip.reference)
    report.check("6. Deduction transporteur", "deduction dans paiement transport", "deduction_amount", money(45000), transport_payment.deduction_amount)
    report.check("6. Deduction transporteur", "solde net transporteur avant reglement", "2 925 000 - 45 000", money(2880000), transport_payment.net_amount)
    report.check("6. Deduction transporteur", "libelle deduction transporteur", "libelle attendu", "Manque quantite - TRIP-TEST-PERTE - 50 L x 900 XOF/L", deduction_label)
    sync_shortage(trip=trip, received_qty=D("44850.00"), unit_selling_price=D("900.0000"))
    report.check("6. Deduction transporteur", "anti doublon deduction", "count apres resauvegarde", 1, TransportDeduction.objects.filter(trip=trip).count())
    sync_shortage(trip=trip, received_qty=D("45000.00"), unit_selling_price=D("900.0000"))
    report.check("6. Deduction transporteur", "deduction remise a zero", "recu 45 000 => aucune deduction", 0, TransportDeduction.objects.filter(trip=trip).count())
    sync_shortage(trip=trip, received_qty=D("44800.00"), unit_selling_price=D("900.0000"))
    deduction = TransportDeduction.objects.get(trip=trip)
    report.check("6. Deduction transporteur", "deduction ajustee 100 L (200 L manquants - 100 L tolerance)", "(200 - 100 tolerance) x 900", money(90000), deduction.amount)
    sync_shortage(trip=trip, received_qty=D("44850.00"), unit_selling_price=D("900.0000"))
    deduction = TransportDeduction.objects.get(trip=trip)
    transport_payment.refresh_from_db()

    invoice = Invoice.objects.get(sale__trip=trip)
    InvoiceService.validate_invoice(invoice.id, user)
    invoice.refresh_from_db()
    report.check("7. Facture client", "quantite facturee", "quantite recue", D("44850.00"), invoice.sale.delivered_quantity)
    report.check("7. Facture client", "facture client", "44 850 x 900", money(40365000), invoice.total_amount)
    report.check("7. Facture client", "dette client", "facture - paiements", money(40365000), PaymentAllocationService.get_customer_outstanding(customer))
    report.check("7. Facture client", "facture visible", "Invoice existe", 1, Invoice.objects.filter(sale__customer=customer).count())

    profit_breakdown = TripProfitService.get_cost_breakdown(trip)
    report.check("11. Benefices", "quantite chargee benefice", "source trajet", D("45000.00"), profit_breakdown["quantity_loaded"])
    report.check("11. Benefices", "quantite recue facturee benefice", "source vente", D("44850.00"), profit_breakdown["quantity_invoiced"])
    report.check("11. Benefices", "perte transporteur benefice", "(45 000 - 44 850) - 100 tolerance", D("50.00"), profit_breakdown["transporter_loss_quantity"])
    report.check("11. Benefices", "indemnisation perte transporteur", "50 x 900", money(45000), profit_breakdown["transporter_loss_indemnity"])
    report.check("11. Benefices", "cout total reel", "45 000 x 800", money(36000000), profit_breakdown["real_total_cost"])
    # Spec 2026-09-07: the 100 L absorbed by the company (150 L loss - 50 L
    # chargeable to the transporter) is still exposed for display, but is no
    # longer a margin term - the client invoice already bills the received
    # quantity, so `revenue` (44 850 x 900) integrates the loss.
    report.check("11. Benefices", "perte absorbee par l'entreprise", "(150 - 50) x 900", money(90000), profit_breakdown["company_absorbed_loss_amount"])
    report.check("11. Benefices", "benefice trajet", "40 365 000 + 45 000 - 36 000 000", money(4410000), profit_breakdown["margin"])
    report.check("11. Benefices", "prix revient benefice", "800 XOF/L", D("800.00"), profit_breakdown["unit_cost"].quantize(D("0.01")))
    report.check("11. Benefices", "benefice par litre", "900 - 800", D("100.00"), profit_breakdown["unit_profit"].quantize(D("0.01")))

    # Task 13 (2026-09-04 recette corrections): no justificatif/proof is
    # ever mandatory anywhere in finance - a customer payment with every
    # other required field but no proof must now validate successfully.
    payment_without_proof = CustomerPaymentSerializer(
        data={
            "customer": customer.id,
            "amount": "20000000.00",
            "payment_date": TODAY.isoformat(),
            "method": CustomerPayment.Method.BANK_TRANSFER,
            "destination": CustomerPayment.Destination.BANK,
            "bank_account": bank.id,
        },
        context={"request": DummyRequest(user)},
    )
    report.check(
        "16. Tests de rejet", "paiement client sans justificatif accepte",
        "proof optionnel (Task 13)", True, payment_without_proof.is_valid(),
    )
    post_customer_payment(customer=customer, amount=money(20000000), bank=bank, invoice=invoice, user=user, reference="PAY-CUST-1")
    bank.refresh_from_db()
    report.check("8. Paiements client", "solde client apres paiement partiel", "40 365 000 - 20 000 000", money(20365000), PaymentAllocationService.get_customer_outstanding(customer))
    report.check("8. Paiements client", "solde banque apres paiement partiel", "200 000 000 + 20 000 000", money(220000000), bank.current_balance)
    report.check("8. Paiements client", "justificatif paiement client", "Document lie", True, TreasuryTransaction.objects.filter(reference="PAY-CUST-1", document__isnull=False).exists())
    post_customer_payment(customer=customer, amount=money(20365000), bank=bank, invoice=invoice, user=user, reference="PAY-CUST-2")
    invoice.refresh_from_db()
    bank.refresh_from_db()
    report.check("8. Paiements client", "solde client final", "40 365 000 - 40 365 000", money(0), PaymentAllocationService.get_customer_outstanding(customer))
    report.check("8. Paiements client", "facture payee", "status PAID", Invoice.Status.PAID, invoice.status)
    report.check("8. Paiements client", "solde banque apres encaissements", "200 000 000 + 40 365 000", money(240365000), bank.current_balance)

    # Bug fix regression (client business rule, confirmed 2026-09-06): "quand
    # les 100 000 L restants sont charges plus tard, la dette et le reliquat
    # se mettent a jour a ce moment-la" - the remaining 55 000 L of this
    # purchase is now loaded (destined for company stock, no further sale
    # workflow needed for this scenario), bringing the reliquat to 0 and the
    # supplier debt up to the full 50 000 000 order value, which the two
    # payments below (30M + 20M) then pay off exactly as originally scripted.
    remaining_cession = CessionLetter.objects.create(
        reference="LC-TEST-001-REMAINDER",
        supplier_order=order,
        authorized_quantity=D("55000.00"),
        issue_date=TODAY,
        created_by=user,
    )
    remaining_truck = Truck.objects.create(
        internal_id="TRK-TEST-REMAINDER",
        tractor_registration="TEST-REMAIN-TRACTOR",
        tanker_registration="TEST-REMAIN-TANKER",
        capacity_litres=D("55000.00"),
        owner_transporter=transporter,
    )
    create_trip(
        reference="TRIP-TEST-REMAINDER",
        quantity=D("55000.00"),
        supplier=supplier,
        order=order,
        cession=remaining_cession,
        product=gasoil,
        transporter=transporter,
        truck=remaining_truck,
        driver=driver,
        user=user,
    )
    report.check("4. Trajet et frais", "reliquat fournisseur apres chargement total", "100 000 - 100 000 charges", D("0.00"), SupplierStockService.get_purchase_reliquat(order))
    report.check("4. Trajet et frais", "dette fournisseur apres chargement total", "100 000 x 500", money(50000000), ControlledDebtPaymentService.describe_supplier(supplier)["remaining_amount"])

    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id,
        bank_account_id=bank.id,
        amount=money(30000000),
        date=TODAY,
        reference="PAY-SUP-1",
        actor=user,
    )
    bank.refresh_from_db()
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "dette fournisseur apres partiel", "50 000 000 - 30 000 000", money(20000000), ControlledDebtPaymentService.describe_supplier(supplier)["remaining_amount"])
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "banque apres fournisseur partiel", "240 365 000 - 30 000 000", money(210365000), bank.current_balance)
    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.SUPPLIER,
        debt_id=supplier.id,
        bank_account_id=bank.id,
        amount=money(20000000),
        date=TODAY,
        reference="PAY-SUP-2",
        actor=user,
    )
    bank.refresh_from_db()
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "dette fournisseur finale", "20 000 000 - 20 000 000", money(0), ControlledDebtPaymentService.describe_supplier(supplier)["remaining_amount"])
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "banque apres fournisseur final", "210 365 000 - 20 000 000", money(190365000), bank.current_balance)

    transporter_debt_before = ControlledDebtPaymentService.describe_transporter(transporter)
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "solde transporteur avant reglement", "2 925 000 - 45 000", money(2880000), transporter_debt_before["remaining_amount"])
    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.TRANSPORTER,
        debt_id=transporter.id,
        bank_account_id=bank.id,
        amount=money(2880000),
        date=TODAY,
        reference="PAY-TRP-1",
        actor=user,
    )
    bank.refresh_from_db()
    transport_payment.refresh_from_db()
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "solde transporteur final", "2 880 000 - 2 880 000", money(0), ControlledDebtPaymentService.describe_transporter(transporter)["remaining_amount"])
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "transporteur brut gagne", "45 000 x 65", money(2925000), transport_payment.base_amount)
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "transporteur deductions", "50 x 900", money(45000), transport_payment.deduction_amount)
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "transporteur deja regle", "paiement effectue", money(2880000), TreasuryTransaction.objects.filter(source_object_id=transport_payment.id, amount=money(2880000)).first().amount)
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "banque apres transporteur", "190 365 000 - 2 880 000", money(187485000), bank.current_balance)

    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.TRANSIT,
        debt_id=0,
        bank_account_id=bank.id,
        amount=money(450000),
        date=TODAY,
        reference="PAY-TRANSIT-1",
        actor=user,
    )
    ControlledDebtPaymentService.record_payment(
        debt_type=ControlledDebtPaymentService.CUSTOMS,
        debt_id=0,
        bank_account_id=bank.id,
        amount=money(10125000),
        date=TODAY,
        reference="PAY-CUSTOMS-1",
        actor=user,
    )
    bank.refresh_from_db()
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "banque apres transit douane", "187 485 000 - 450 000 - 10 125 000", money(176910000), bank.current_balance)
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "dette transit", "450 000 - 450 000", money(0), ControlledDebtPaymentService.describe_expense_group(ControlledDebtPaymentService.TRANSIT)["remaining_amount"])
    report.check("9. Paiements fournisseur / transporteur / douane / transit", "dette douane", "10 125 000 - 10 125 000", money(0), ControlledDebtPaymentService.describe_expense_group(ControlledDebtPaymentService.CUSTOMS)["remaining_amount"])

    report.check("10. Tresorerie finale", "banques", "200M + 40.365M - 50M - 2.88M - .45M - 10.125M", money(176910000), bank.current_balance)
    report.check("10. Tresorerie finale", "caisses", "5 000 000", money(5000000), cash.current_balance)
    report.check("10. Tresorerie finale", "total tresorerie", "176 910 000 + 5 000 000", money(181910000), bank.current_balance + cash.current_balance)

    distribution = ShareholderDistributionService.create_distribution(TODAY, TODAY, money(4410000), user)
    ShareholderDistributionService.validate_distribution(distribution.id, user)
    shares = {share.shareholder.name: share for share in ShareholderProfitShare.objects.filter(distribution=distribution).select_related("shareholder")}
    report.check("12. Repartition actionnaires", "part Abdou", "4 410 000 x 10%", money(441000), shares["Abdou Mohamed"].amount_due)
    report.check("12. Repartition actionnaires", "part Sidi", "4 410 000 x 80%", money(3528000), shares["Sidi Mohamed"].amount_due)
    report.check("12. Repartition actionnaires", "part Yacoub", "4 410 000 x 10%", money(441000), shares["Yacoub"].amount_due)
    report.check("12. Repartition actionnaires", "benefice restant non retire", "somme parts", money(4410000), sum(share.remaining_due for share in shares.values()))

    ShareholderWithdrawalService.record_withdrawal(
        shareholder_id=shareholders["Sidi Mohamed"].id,
        profit_share_id=shares["Sidi Mohamed"].id,
        amount=money(1000000),
        date=TODAY,
        bank_account_id=bank.id,
        actor=user,
    )
    bank.refresh_from_db()
    shares["Sidi Mohamed"].refresh_from_db()
    report.check("13. Retraits / avances", "solde disponible Sidi apres retrait", "3 528 000 - 1 000 000", money(2528000), ShareholderLedgerService.get_available_balance(shareholders["Sidi Mohamed"].id))
    report.check("13. Retraits / avances", "banque apres retrait", "176 910 000 - 1 000 000", money(175910000), bank.current_balance)
    report.check("13. Retraits / avances", "grand livre retrait Sidi", "ligne WITHDRAWAL", True, any(row["type"] == "WITHDRAWAL" and row["debit"] == money(1000000) for row in ShareholderStatementQuery.run(shareholder_id=shareholders["Sidi Mohamed"].id)))
    before_loan_tx_count = TreasuryTransaction.objects.count()
    ShareholderLoanService.create_loan(
        lender_id=shareholders["Sidi Mohamed"].id,
        borrower_id=shareholders["Abdou Mohamed"].id,
        amount=money(500000),
        date=TODAY,
    )
    report.check("13. Retraits / avances", "avance sans tresorerie", "nb transactions inchange", before_loan_tx_count, TreasuryTransaction.objects.count())
    report.check("13. Retraits / avances", "grand livre avance preteur", "ligne LOAN_GIVEN", True, any(row["type"] == "LOAN_GIVEN" and row["credit"] == money(500000) for row in ShareholderStatementQuery.run(shareholder_id=shareholders["Sidi Mohamed"].id)))
    report.check("13. Retraits / avances", "grand livre avance emprunteur", "ligne LOAN_RECEIVED", True, any(row["type"] == "LOAN_RECEIVED" and row["debit"] == money(500000) for row in ShareholderStatementQuery.run(shareholder_id=shareholders["Abdou Mohamed"].id)))

    cession_stock = CessionLetter.objects.create(
        reference="LC-TEST-STOCK",
        supplier_order=order,
        authorized_quantity=D("10000.00"),
        issue_date=TODAY,
        created_by=user,
    )
    stock_trip = create_trip(
        reference="TRIP-TEST-STOCK",
        quantity=D("10000.00"),
        supplier=supplier,
        order=order,
        cession=cession_stock,
        product=gasoil,
        transporter=transporter,
        truck=truck,
        driver=driver,
        user=user,
    )
    stock_trip = transition_path(
        stock_trip,
        [
            Trip.Status.SENT_FOR_LOADING,
            Trip.Status.LOADING,
            Trip.Status.LOADED,
            Trip.Status.ROAD_TRANSIT,
            Trip.Status.IN_TRANSIT,
            Trip.Status.BORDER,
            Trip.Status.CUSTOMS,
            Trip.Status.GOING_TO_COMPANY_STOCK,
            Trip.Status.ARRIVED_AT_COMPANY_STOCK,
            Trip.Status.STOCKED,
        ],
        user,
    )
    report.check("14. Dashboard", "stock entreprise trajet present", "TRIP-TEST-STOCK stocked", 1, Trip.objects.filter(reference="TRIP-TEST-STOCK", destination_type=Trip.DestinationType.COMPANY_STOCK, status=Trip.Status.STOCKED).count())
    company_stock_qty = Trip.objects.filter(destination_type=Trip.DestinationType.COMPANY_STOCK, status__in=[Trip.Status.ARRIVED_AT_COMPANY_STOCK, Trip.Status.STOCKED]).aggregate(total=__import__("django.db.models").db.models.Sum("quantity_loaded"))["total"]
    report.check("14. Dashboard", "stock entreprise dashboard", "10 000 L", D("10000.00"), company_stock_qty)
    report.check("14. Dashboard", "statuts client bloques sans client", "STOCKED allowed excludes GOING_TO_CLIENT avant client", False, Trip.Status.GOING_TO_CLIENT in TripWorkflowService.get_allowed_targets(stock_trip))
    TripCostService.assign_customer_for_sale(stock_trip.id, customer.id, user)
    stock_trip.refresh_from_db()
    report.check("14. Dashboard", "sortie stock apres attribution", "destination CUSTOMER", Trip.DestinationType.CUSTOMER, stock_trip.destination_type)
    report.check("14. Dashboard", "workflow client apres attribution", "GOING_TO_CLIENT permis", True, Trip.Status.GOING_TO_CLIENT in TripWorkflowService.get_allowed_targets(stock_trip))

    report.check("15. Grands livres", "compte client total facture", "invoice ledger debit", money(40365000), sum((row["debit"] or money(0)) for row in CustomerStatementQuery.run(customer_id=customer.id)))
    report.check("15. Grands livres", "compte client total encaisse", "payment ledger credit", money(40365000), sum((row["credit"] or money(0)) for row in CustomerStatementQuery.run(customer_id=customer.id)))
    report.check("15. Grands livres", "compte fournisseur total achete", "supplier ledger debit", money(50000000), sum((row["debit"] or money(0)) for row in SupplierStatementQuery.run(supplier_id=supplier.id)))
    report.check("15. Grands livres", "compte fournisseur total paye", "supplier ledger credit", money(50000000), sum((row["credit"] or money(0)) for row in SupplierStatementQuery.run(supplier_id=supplier.id)))
    transporter_rows = TransporterStatementQuery.run(transporter_id=transporter.id)
    report.check("15. Grands livres", "grand livre transporteur deduction", "deduction_amount", money(45000), transporter_rows[0]["deduction_amount"])
    report.check("15. Grands livres", "grand livre transporteur net", "net_amount", money(2880000), transporter_rows[0]["net_amount"])
    report.check("15. Grands livres", "journal tresorerie banque final", "dernier solde", money(175910000), TreasuryStatementQuery.run(bank_account_id=bank.id)[-1]["balance"])

    def rejected(label, fn, exc_type=Exception):
        try:
            fn()
        except exc_type:
            report.check("16. Tests de rejet", label, "exception attendue", True, True)
        else:
            report.check("16. Tests de rejet", label, "exception attendue", True, False)

    rejected(
        "paiement fournisseur superieur dette",
        lambda: ControlledDebtPaymentService.record_payment(
            debt_type=ControlledDebtPaymentService.SUPPLIER,
            debt_id=supplier.id,
            bank_account_id=bank.id,
            amount=money(1),
            date=TODAY,
            reference="REJECT-SUP-DEBT",
            actor=user,
        ),
        ControlledDebtPaymentError,
    )
    rejected(
        "paiement fournisseur superieur solde bancaire",
        lambda: ControlledDebtPaymentService.record_payment(
            debt_type=ControlledDebtPaymentService.SUPPLIER,
            debt_id=supplier.id,
            bank_account_id=bank.id,
            amount=money(999000000),
            date=TODAY,
            reference="REJECT-SUP-BANK",
            actor=user,
        ),
        ControlledDebtPaymentError,
    )
    rejected(
        "paiement transporteur superieur solde net",
        lambda: ControlledDebtPaymentService.record_payment(
            debt_type=ControlledDebtPaymentService.TRANSPORTER,
            debt_id=transporter.id,
            bank_account_id=bank.id,
            amount=money(1),
            date=TODAY,
            reference="REJECT-TRP-DEBT",
            actor=user,
        ),
        ControlledDebtPaymentError,
    )
    rejected(
        "retrait actionnaire superieur solde disponible",
        lambda: ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholders["Yacoub"].id,
            amount=money(999000000),
            date=TODAY,
            bank_account_id=bank.id,
            actor=user,
        ),
        ShareholderWithdrawalError,
    )
    small_bank = BankAccount.objects.create(name="Banque Minuscule", opening_balance=money(10))
    rejected(
        "retrait actionnaire superieur solde banque",
        lambda: ShareholderWithdrawalService.record_withdrawal(
            shareholder_id=shareholders["Yacoub"].id,
            amount=money(100),
            date=TODAY,
            bank_account_id=small_bank.id,
            actor=user,
        ),
        ShareholderWithdrawalError,
    )
    rejected(
        "avance actionnaire vers lui-meme",
        lambda: ShareholderLoan.objects.create(
            lender=shareholders["Sidi Mohamed"],
            borrower=shareholders["Sidi Mohamed"],
            amount=money(1),
            date=TODAY,
        ),
        Exception,
    )
    rejected(
        "avance depuis actionnaire sans solde",
        lambda: ShareholderLoanService.create_loan(
            lender_id=shareholders["Abdou Mohamed"].id,
            borrower_id=shareholders["Yacoub"].id,
            amount=money(999000000),
            date=TODAY,
        ),
        ShareholderLoanError,
    )
    stock_trip = TripWorkflowService.transition_trip(stock_trip.id, Trip.Status.GOING_TO_CLIENT, user)
    stock_trip = TripWorkflowService.transition_trip(stock_trip.id, Trip.Status.ARRIVED_AT_CLIENT, user)
    # Client correction (2026-09-04 recette): QUANTITY_CONTROL is no longer
    # a mandatory intermediate stop before DELIVERED.
    rejected(
        "prix vente inferieur prix revient sans confirmation",
        lambda: DeliveryService.record_delivery(
            stock_trip.id,
            received_qty=D("10000.00"),
            control_date=TODAY,
            method=DeliveryControl.Method.MANUAL_GAUGE,
            controller=user,
            unit_selling_price=D("400.0000"),
        ),
        SaleBelowCostConfirmationRequired,
    )
    report.check("16. Tests de rejet", "deduction transporteur creee deux fois", "count reste 1", 1, TransportDeduction.objects.filter(trip=trip).count())

    report.print()
    captured = capsys.readouterr()
    print(captured.out)
