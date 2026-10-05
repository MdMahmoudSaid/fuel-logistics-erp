from rest_framework.permissions import BasePermission

ACTION_MAP = {
    "list": "view",
    "retrieve": "view",
    "ledger": "view",
    # PDF export of a party ledger (Task 10, recette corrections 2026-09-04)
    # is read-only - same "view" tier as `ledger` itself, just a different
    # response format via a dedicated action (DRF reserves the `format`
    # query param for its own content negotiation, so this can't be a
    # branch on `ledger` gated by `?format=pdf`).
    "ledger_pdf": "view",
    # Per-trip settlement PDF export (Task 11, same design doc) - read-only
    # print of an existing TransportPayment, same "view" tier.
    "pdf": "view",
    "reliquat": "view",
    "next_reference": "view",
    "trips": "view",
    "history": "view",
    "allowed_statuses": "view",
    "margin": "view",
    # Delivery form's price pre-fill lookup (see "delivery_control" below) -
    # same "view" tier as margin, no write happens here.
    "suggested_selling_price": "view",
    # Dashboard's single custom read action (docs/PHASE_6_PLAN.md Etape 5).
    "summary": "view",
    "working_capital_pdf": "view",
    "payable_debts": "view",
    "party_balances": "view",
    # Bug fix (found 2026-09-06): missing from this map entirely, so it
    # fell back to the literal action name "profit_preview" - never a
    # valid tier in Role.ACTIONS, so `role.has_permission("shareholders",
    # "profit_preview")` was False for every non-superuser role no matter
    # what permissions they actually held. Every previous manual recette
    # missed this because it ran as an admin/superuser, who bypasses
    # HasModulePermission entirely - this endpoint is read-only ("Task 7,
    # client modifications plan" docstring), same "view" tier as `ledger`.
    "profit_preview": "view",
    # PDF export of the Benefices page (client request 2026-09-06) - same
    # "view" tier as profit_preview above and every other PDF export in
    # this map (ledger_pdf, pdf): read-only, never worth gating behind a
    # separate tier. Added explicitly rather than left to fall through to
    # its own action name, unlike profit_preview's own gap above (fixed
    # 2026-09-06) which is exactly why this one isn't skipped.
    "profit_preview_pdf": "view",
    # Sum of every active shareholder's real ledger balance (client request
    # 2026-09-16) - read-only, same "view" tier as `ledger`/`profit_preview`
    # above. Listed explicitly to avoid the exact profit_preview gap fixed
    # 2026-09-06: a custom action missing from this map silently falls back
    # to its own name, which is never a valid Role.ACTIONS tier.
    "balances": "view",
    "create": "create",
    "update": "edit",
    "partial_update": "edit",
    # Closing/reopening a profit period changes the accounting state and is
    # therefore restricted to roles that may validate shareholder records.
    "close": "validate",
    "reopen": "validate",
    # Idempotent system rollover: a viewer may trigger it, but cannot choose
    # or alter any dates.  The server derives the next start date from the
    # latest closed period and records the authenticated actor in the audit.
    "ensure_current": "view",
    # Trip status transitions (docs/PHASE_3_PLAN.md Etape 6) are routine
    # day-to-day operations work, not a "validate" business action - map to
    # "edit" so the Operations role (which has edit but not validate on the
    # operations module) can drive a trip through its lifecycle.
    "status": "edit",
    "destroy": "cancel",
    # Delivery confirmation (docs/PHASE_4_PLAN.md Etape 6) is the same kind
    # of routine operations action as a trip status transition above.
    "delivery_control": "edit",
    # Post-delivery client quantity check (recette corrections Task 6,
    # 2026-09-04) corrects an existing DeliveryControl - same routine
    # operations tier as the delivery confirmation it follows.
    "client_verification": "edit",
    # A correction only ever applies to an already-verified DeliveryControl
    # and is audited (ClientVerificationCorrection) - same "validate" tier
    # as an invoice correction ("correct" above), not the routine "edit"
    # tier used by the first verification.
    "correct_client_verification": "validate",
    # Trip cost basis (Task 1, client modifications plan) is a read-only
    # decomposition, same "view" tier as margin/suggested_selling_price.
    "cost_basis": "view",
    # Assigning a direct customer to a trip is routine operations work,
    # same "edit" tier as a trip status transition/delivery confirmation.
    "assign_customer": "edit",
    "assign_customers": "edit",
    # Invoice validation freezes financial data - gate it behind "validate"
    # (Role.ACTIONS), same tier as SupplierOrder/CessionLetter confirmation.
    "validate": "validate",
    "bulk_validate": "validate",
    # A correction only ever applies to an already-VALIDATED invoice, so it
    # requires the same "validate" tier rather than plain "edit".
    "correct": "validate",
    # Editing a DRAFT invoice's price (feedback 2026-09-10) is a plain,
    # unaudited edit - same "edit" tier as `update`/`partial_update` on a
    # DRAFT invoice, not the "validate" tier `correct` above requires.
    "update_price": "edit",
    # Both create new financial records via a dedicated service rather than
    # a plain model create, but are still "create" tier from a permissions
    # standpoint (docs/PHASE_5_PLAN.md Etape 6/8).
    "transfer": "create",
    "record_indirect": "create",
    "record_customer_paid": "create",
    "record_debt_payment": "create",
    # Applying an already-recorded customer receipt changes only its invoice
    # allocation (and the derived invoice payment status).  It does not create
    # a new receipt or treasury movement, so it belongs to the edit tier.
    "allocate": "edit",
    # Recording a ShareholderLoan repayment (Task 7, client modifications
    # plan, lost-update race fix) mutates an existing loan row exactly like
    # a plain PATCH would have - same "edit" tier as `update`/
    # `partial_update`, just routed through a dedicated atomic action
    # instead of a raw field write.
    "record_repayment": "edit",
    # Duplicating a quotation produces a new DRAFT record - same "create"
    # tier as a plain POST.
    "duplicate": "create",
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
