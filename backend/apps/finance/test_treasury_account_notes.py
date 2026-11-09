# A bank / cash account can carry a free-text note (e.g. why an opening balance
# is negative), returned by the API so the list can show it.

from decimal import Decimal

import pytest

from apps.finance.models import BankAccount, CashAccount
from apps.finance.serializers import BankAccountSerializer, CashAccountSerializer


@pytest.mark.django_db
def test_bank_account_note_round_trips():
    serializer = BankAccountSerializer(
        data={
            "name": "BDM",
            "opening_balance": "-517522272.00",
            "notes": "Ajustement de depart pour regler la situation.",
        }
    )
    assert serializer.is_valid(), serializer.errors
    account = serializer.save()

    assert BankAccountSerializer(account).data["notes"] == "Ajustement de depart pour regler la situation."
    assert account.opening_balance == Decimal("-517522272.00")


@pytest.mark.django_db
def test_notes_are_optional_and_default_to_empty():
    assert BankAccount.objects.create(name="B").notes == ""
    assert CashAccountSerializer(CashAccount.objects.create(name="C")).data["notes"] == ""
