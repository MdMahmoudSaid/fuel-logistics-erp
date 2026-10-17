# One-time setup (client request 2026-10-17): the profit made in the previous
# application, counted in the all-time net profit (card "Benefice net apres
# depenses generales", "Benefice a distribuer") and distributed at the next
# period closure. No treasury movement: the money is already in the accounts'
# opening balances.
#
#   python manage.py set_brought_forward_profit 92358500          # dry run
#   python manage.py set_brought_forward_profit 92358500 --apply
#   python manage.py set_brought_forward_profit 0 --apply         # remove it

from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import CompanyProfile
from apps.finance.models import ShareholderProfitDistribution


class Command(BaseCommand):
    help = "Set the profit brought forward from the previous application."

    def add_arguments(self, parser):
        parser.add_argument("amount")
        parser.add_argument("--apply", action="store_true", help="write it (default: show only)")

    def handle(self, *args, **options):
        try:
            amount = Decimal(options["amount"]).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise CommandError("Montant invalide.")
        if amount < 0:
            raise CommandError("Le montant ne peut pas etre negatif.")
        profile = CompanyProfile.load()
        self.stdout.write(f"Benefice reporte actuel : {profile.brought_forward_profit}")
        self.stdout.write(f"Nouveau benefice reporte : {amount}")
        if not options["apply"]:
            self.stdout.write("Simulation : relancer avec --apply pour l'enregistrer.")
            return
        # Changing an amount that may already have been distributed would falsify
        # what was shared; setting it for the first time is always safe.
        if (
            profile.brought_forward_profit
            and amount != profile.brought_forward_profit
            and ShareholderProfitDistribution.objects.filter(
                status=ShareholderProfitDistribution.Status.VALIDATED
            ).exists()
        ):
            raise CommandError(
                "Des repartitions validees existent : modifier le benefice reporte fausserait "
                "ce qui a deja ete reparti."
            )
        profile.brought_forward_profit = amount
        profile.save(update_fields=["brought_forward_profit", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Benefice reporte enregistre : {amount}"))
