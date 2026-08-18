from rest_framework.permissions import BasePermission

ACTION_MAP = {
    "list": "view",
    "retrieve": "view",
    "ledger": "view",
    "reliquat": "view",
    "trips": "view",
    "history": "view",
    "create": "create",
    "update": "edit",
    "partial_update": "edit",
    # Trip status transitions (docs/PHASE_3_PLAN.md Etape 6) are routine
    # day-to-day operations work, not a "validate" business action - map to
    # "edit" so the Operations role (which has edit but not validate on the
    # operations module) can drive a trip through its lifecycle.
    "status": "edit",
    "destroy": "cancel",
    # Delivery confirmation (docs/PHASE_4_PLAN.md Etape 6) is the same kind
    # of routine operations action as a trip status transition above.
    "delivery_control": "edit",
    # Invoice validation freezes financial data - gate it behind "validate"
    # (Role.ACTIONS), same tier as SupplierOrder/CessionLetter confirmation.
    "validate": "validate",
    # A correction only ever applies to an already-VALIDATED invoice, so it
    # requires the same "validate" tier rather than plain "edit".
    "correct": "validate",
}


class HasModulePermission(BasePermission):
    """Gate ViewSet actions by the caller's Role permission matrix.

    Set `module = "<one of Role.MODULES>"` as a class attribute on any
    ViewSet using this permission class. Superusers bypass the check.
    """

    module: str | None = None

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        module = getattr(view, "module", self.module)
        action = ACTION_MAP.get(view.action, view.action)

        role = request.user.role
        if role is None or module is None:
            return False
        return role.has_permission(module, action)
