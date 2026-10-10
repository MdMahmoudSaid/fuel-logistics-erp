"""One-off repair for the automatic distribution of customer receipts
(2026-10-10): before it, a receipt recorded as "crédit non affecté" stayed
unallocated even when the customer still had an open invoice, so the ledger
showed a zero balance next to a "Partiellement payée" invoice. Applies every
such open credit to the customer's open invoices, oldest first - exactly what
saving a payment now does on its own. Idempotent.

Dry run by default (lists what would change); --apply writes.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.customers.models import Customer
from apps.finance.services import ZERO, PaymentAllocationService
from apps.sales.models import Invoice


class Command(BaseCommand):
    help = "Affecte le credit non affecte des clients a leurs factures ouvertes."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Ecrit les affectations (sinon simulation).")

    def handle(self, *args, **options):
        apply = options["apply"]
        touched = 0
        for customer in Customer.objects.order_by("id"):
            credit = PaymentAllocationService.get_customer_available_credit(customer)
            if credit <= ZERO:
                continue
            open_invoices = [
                invoice
                for invoice in Invoice.objects.filter(
                    sale__customer=customer,
                    status__in=(Invoice.Status.VALIDATED, Invoice.Status.PARTIALLY_PAID),
                ).order_by("issued_date", "id")
                if PaymentAllocationService.get_invoice_outstanding(invoice) > ZERO
            ]
            if not open_invoices:
                continue
            touched += 1
            due = sum((PaymentAllocationService.get_invoice_outstanding(i) for i in open_invoices), ZERO)
            numbers = ", ".join(i.invoice_number for i in open_invoices)
            self.stdout.write(
                f"{customer.name} : credit {credit} / factures ouvertes {due} ({numbers})"
            )
            if apply:
                with transaction.atomic():
                    applied = PaymentAllocationService.apply_customer_credit_to_open_invoices(customer)
                self.stdout.write(f"  -> {applied} affecte")
        verb = "corrige(s)" if apply else "a corriger (relancer avec --apply)"
        self.stdout.write(f"{touched} client(s) {verb}.")
