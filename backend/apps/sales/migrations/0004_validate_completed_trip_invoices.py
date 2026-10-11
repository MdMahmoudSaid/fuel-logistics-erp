# Client request 2026-10-11: a completed trip's invoice is now validated
# automatically (TripWorkflowService.transition_trip). This catches up the
# invoices left DRAFT by trips completed before that rule existed, so the
# receipts already sitting as customer credit get imputed on them.

from django.db import migrations


def validate_completed_trip_invoices(apps, schema_editor):
    Invoice = apps.get_model("sales", "Invoice")
    candidates = []
    for invoice in Invoice.objects.filter(status="DRAFT").order_by("issued_date", "id"):
        trips = [invoice.sale.trip, *(s.trip for s in invoice.extra_sales.all())]
        if all(trip.status == "COMPLETED" for trip in trips):
            candidates.append(invoice.id)
    if not candidates:
        return
    # The live service (not the historical models) is what imputes the
    # customer's open credit; only reached when there is data to fix.
    from apps.sales.services import InvoiceService

    for invoice_id in candidates:
        InvoiceService.validate_invoice(invoice_id, None)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0003_multi_trip_invoice"),
        ("trips", "0011_multi_trip_invoice"),
        ("finance", "0028_opening_debt_customer_advance"),
    ]

    operations = [
        migrations.RunPython(validate_completed_trip_invoices, migrations.RunPython.noop),
    ]
