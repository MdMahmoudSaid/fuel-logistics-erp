from django.contrib.contenttypes.models import ContentType

from .models import AdvanceConsumption, TransportPayment, TreasuryTransaction


def can_modify_commission(payment):
    """Only unsettled commissions without financial history can be changed."""
    if payment.status not in (
        TransportPayment.Status.PLANNED,
        TransportPayment.Status.PAYABLE,
        TransportPayment.Status.DEDUCTION_APPLIED,
    ) or payment.advance_applied_id:
        return False
    content_type = ContentType.objects.get_for_model(TransportPayment)
    return not (
        AdvanceConsumption.objects.filter(
            debt_content_type=content_type, debt_object_id=payment.pk,
        ).exists()
        or TreasuryTransaction.objects.filter(
            source_content_type=content_type, source_object_id=payment.pk,
        ).exists()
    )
