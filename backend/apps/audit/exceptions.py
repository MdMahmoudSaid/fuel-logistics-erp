class HardDeleteBlocked(Exception):
    """Raised when code attempts to physically delete an AuditableModel
    record that has moved past its draft state (docs/PHASE_6_PLAN.md
    Etape 1; ERP_Implementation_Experience_Guide.md Section 1.C:
    cancellation, not deletion, is the only path for a validated financial
    record)."""
