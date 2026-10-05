from django.contrib.contenttypes.models import ContentType

from apps.core.request_cache import memoize_per_request

from .models import AdvanceConsumption, TransportPayment, TreasuryTransaction


def can_modify_commission(payment):
    """Only unsettled commissions without financial history can be changed."""
    if payment.status not in (
        TransportPayment.Status.PLANNED,
        TransportPayment.Status.PAYABLE,
        TransportPayment.Status.DEDUCTION_APPLIED,
    ) or payment.advance_applied_id:
        return False
    return not _has_financial_history(payment.pk)


@memoize_per_request
def _has_financial_history(payment_id) -> bool:
    content_type = ContentType.objects.get_for_model(TransportPayment)
    return (
        AdvanceConsumption.objects.filter(
            debt_content_type=content_type, debt_object_id=payment_id,
        ).exists()
        or TreasuryTransaction.objects.filter(
            source_content_type=content_type, source_object_id=payment_id,
        ).exists()
    )


def prime_commission_history(payments) -> None:
    """Answer _has_financial_history for a whole list page in two queries
    (same filters as above - keep them in step)."""
    ids = [payment.pk for payment in payments if payment.pk is not None]
    if not ids:
        return
    content_type = ContentType.objects.get_for_model(TransportPayment)
    with_history = set(
        AdvanceConsumption.objects.filter(
            debt_content_type=content_type, debt_object_id__in=ids
        ).values_list("debt_object_id", flat=True)
    ) | set(
        TreasuryTransaction.objects.filter(
            source_content_type=content_type, source_object_id__in=ids
        ).values_list("source_object_id", flat=True)
    )
    for payment_id in ids:
        _has_financial_history.prime(payment_id in with_history, payment_id)
