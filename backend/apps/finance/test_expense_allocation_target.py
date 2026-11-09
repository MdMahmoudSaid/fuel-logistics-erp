# An expense allocation must point at an entity (content_type + object_id).
# Found on AZUR 2026-11-09: a 10,000 loading fee had object_id=8 and
# content_type=NULL, so it belonged to no trip margin and was not a general
# expense either - the money left the treasury but reached no profit.

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.finance.serializers import ExpenseAllocationInputSerializer
from apps.trips.models import Trip


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["content_type", "object_id", "both"])
def test_allocation_without_a_full_target_is_rejected(missing):
    data = {
        "content_type": ContentType.objects.get_for_model(Trip).pk,
        "object_id": 8,
        "allocated_amount": Decimal("10000.00"),
    }
    if missing in ("content_type", "both"):
        data.pop("content_type")
    if missing in ("object_id", "both"):
        data.pop("object_id")

    serializer = ExpenseAllocationInputSerializer(data=data)

    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


@pytest.mark.django_db
def test_allocation_with_a_full_target_is_accepted():
    serializer = ExpenseAllocationInputSerializer(
        data={
            "content_type": ContentType.objects.get_for_model(Trip).pk,
            "object_id": 8,
            "allocated_amount": "10000.00",
        }
    )

    assert serializer.is_valid(), serializer.errors
