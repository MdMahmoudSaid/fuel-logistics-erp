from rest_framework.permissions import BasePermission

ACTION_MAP = {
    "list": "view",
    "retrieve": "view",
    "ledger": "view",
    "reliquat": "view",
    "next_reference": "view",
    "trips": "view",
    "history": "view",
    "margin": "view",
    # Delivery form's price pre-fill lookup (see "delivery_control" below) -
    # same "view" tier as margin, no write happens here.
    "suggested_selling_price": "view",
    # Dashboard's single custom read action (docs/PHASE_6_PLAN.md Etape 5).
    "summary": "view",
    "payable_debts": "view",
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
    # Trip cost basis (Task 1, client modifications plan) is a read-only
    # decomposition, same "view" tier as margin/suggested_selling_price.
    "cost_basis": "view",
    # Assigning a direct customer to a trip is routine operations work,
    # same "edit" tier as a trip status transition/delivery confirmation.
    "assign_customer": "edit",
    # Invoice validation freezes financial data - gate it behind "validate"
    # (Role.ACTIONS), same tier as SupplierOrder/CessionLetter confirmation.
    "validate": "validate",
    # A correction only ever applies to an already-VALIDATED invoice, so it
    # requires the same "validate" tier rather than plain "edit".
    "correct": "validate",
    # Both create new financial records via a dedicated service rather than
    # a plain model create, but are still "create" tier from a permissions
    # standpoint (docs/PHASE_5_PLAN.md Etape 6/8).
    "transfer": "create",
    "record_indirect": "create",
    "record_debt_payment": "create",
    # Recording a ShareholderLoan repayment (Task 7, client modifications
    # plan, lost-update race fix) mutates an existing loan row exactly like
    # a plain PATCH would have - same "edit" tier as `update`/
    # `partial_update`, just routed through a dedicated atomic action
    # instead of a raw field write.
    "record_repayment": "edit",
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
