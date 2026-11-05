"""Account status shared by customers, suppliers and transporters.

Three states, derived from two booleans:

* active   - is_active and not is_legacy: still trading, offered everywhere.
* legacy   - is_legacy ("Ancien"): no longer trading but money is still owed
             one way or the other. Never offered when creating new business
             (is_legacy always implies is_active=False, so every existing
             ``is_active=true`` picker excludes them); still offered where a
             balance gets settled.
* inactive - not is_active and not is_legacy: fully settled, archived.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import serializers, status
from rest_framework.response import Response

# Parties whose account is still live: working (active) or no longer working
# but not settled yet (legacy). Use it for every balance / debt aggregate.
from django.db.models import Q as _Q

HAS_OPEN_ACCOUNT = _Q(is_active=True) | _Q(is_legacy=True)

ACCOUNT_STATUSES = ("active", "legacy", "inactive")


def filter_by_account_status(queryset, raw: str | None):
    """Apply ``?status=active,legacy`` (comma list) to a queryset."""
    if not raw:
        return queryset
    from django.db.models import Q

    wanted = {s.strip() for s in raw.split(",") if s.strip() in ACCOUNT_STATUSES}
    if not wanted:
        return queryset
    query = Q(pk__in=[])
    if "active" in wanted:
        query |= Q(is_active=True, is_legacy=False)
    if "legacy" in wanted:
        query |= Q(is_legacy=True)
    if "inactive" in wanted:
        query |= Q(is_active=False, is_legacy=False)
    return queryset.filter(query)


class AccountStatusFilterMixin:
    """ViewSet mixin: adds the ``status`` query filter on list."""

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = filter_by_account_status(queryset, self.request.query_params.get("status"))
        return queryset


class AccountStatusSerializerMixin:
    """Serializer mixin: keeps is_active/is_legacy coherent and refuses to
    archive (is_active=False) a record that still has open business.

    Subclasses implement ``status_blockers(instance)`` returning a list of
    short French reasons ("solde non nul", "camion en cours de trajet"...);
    a non-empty list blocks the move to *inactive*. Moving to "Ancien"
    (customers, suppliers, transporters) is never blocked: that is exactly
    the place for an account that is not settled yet.
    Runs in to_internal_value so a serializer's own validate() cannot bypass
    or be broken by it.
    """

    def status_blockers(self, instance) -> list[str]:
        return []

    def to_internal_value(self, data):
        attrs = super().to_internal_value(data)
        instance = self.instance
        is_legacy = attrs.get("is_legacy", getattr(instance, "is_legacy", False))
        is_active = attrs.get("is_active", getattr(instance, "is_active", True))
        if attrs.get("is_legacy"):
            # Moving to "Ancien" wins over a stale is_active flag.
            attrs["is_active"] = False
            is_active = False
        elif attrs.get("is_active"):
            attrs["is_legacy"] = False
            is_legacy = False
        becoming_inactive = not is_active and not is_legacy
        was_inactive = instance is not None and not instance.is_active and not getattr(
            instance, "is_legacy", False
        )
        if instance is not None and becoming_inactive and not was_inactive:
            blockers = self.status_blockers(instance)
            if blockers:
                hint = (
                    " Passez-le en « Ancien » tant que les comptes ne sont pas soldés."
                    if hasattr(instance, "is_legacy")
                    else ""
                )
                raise serializers.ValidationError(
                    {
                        "is_active": (
                            "Désactivation impossible : " + " ; ".join(blockers) + "." + hint
                        )
                    }
                )
        return attrs


class RejectInactiveMixin:
    """Serializer mixin: a record that is inactive (or "Ancien") must not be
    picked for NEW business. ``reject_inactive_fields`` lists the relation
    fields to check. Only a value being set or changed is checked, so
    editing an old record that already points at a now-inactive one still
    works."""

    reject_inactive_fields: tuple[str, ...] = ()

    def to_internal_value(self, data):
        attrs = super().to_internal_value(data)
        errors = {}
        for field in self.reject_inactive_fields:
            value = attrs.get(field)
            if value is None or getattr(value, "is_active", True):
                continue
            if self.instance is not None and getattr(self.instance, field, None) == value:
                continue
            errors[field] = "Cet élément est inactif : il ne peut plus être utilisé."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class InactiveOnlyDeleteMixin:
    """ViewSet mixin: permanent deletion, only for an inactive record.

    An active or "Ancien" record must be deactivated first (which itself is
    refused while it has open work or a balance). A record that history still
    points at (trips, invoices, payments...) cannot disappear: that comes back
    as a clear 409 instead of a server error.
    """

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj == request.user:
            return Response(
                {"detail": "Vous ne pouvez pas supprimer votre propre compte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if getattr(obj, "is_active", False) or getattr(obj, "is_legacy", False):
            return Response(
                {"detail": "Désactivez d'abord cet élément avant de le supprimer définitivement."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            with transaction.atomic():
                self.perform_destroy(obj)
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Suppression impossible : cet élément est lié à des opérations "
                        "existantes. Laissez-le inactif."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
