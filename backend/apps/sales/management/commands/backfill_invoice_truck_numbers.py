"""Append the truck number to invoices issued before it was part of the
number (FAC-202611-0002 -> FAC-202611-0002-AA123BB).

Dry run by default: prints what would change. Pass --apply to write.
Renaming an issued invoice number is deliberate and irreversible from the
UI, so run it only after checking the dry run (and after a DB backup).
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.sales.models import Invoice
from apps.trips.models import TripCustomerRefusal
from apps.trips.services import invoice_truck_token

_BASE = re.compile(r"^FAC-\d{6}-\d{4}$")


class Command(BaseCommand):
    help = "Append the truck number to old invoice numbers (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the new numbers.")

    def handle(self, *args, **options):
        apply = options["apply"]
        changed = skipped = 0
        invoices = Invoice.objects.select_related("sale__trip__truck").prefetch_related(
            "extra_sales__trip__truck"
        )
        with transaction.atomic():
            for invoice in invoices.order_by("id"):
                if not _BASE.match(invoice.invoice_number):
                    skipped += 1  # already carries a suffix, or a hand-typed format
                    continue
                token = invoice_truck_token(invoice.all_sales)
                if not token:
                    skipped += 1
                    continue
                new_number = f"{invoice.invoice_number}-{token}"
                self.stdout.write(f"{invoice.invoice_number} -> {new_number}")
                changed += 1
                if apply:
                    TripCustomerRefusal.objects.filter(invoice_number=invoice.invoice_number).update(
                        invoice_number=new_number
                    )
                    invoice.invoice_number = new_number
                    invoice.save(update_fields=["invoice_number", "updated_at"])
            if not apply:
                transaction.set_rollback(True)
        verb = "Renamed" if apply else "Would rename"
        self.stdout.write(self.style.SUCCESS(f"{verb} {changed} invoice(s); skipped {skipped}."))
