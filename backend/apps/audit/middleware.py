from apps.audit.context import bind_current_request, clear_current_request


class CurrentRequestMiddleware:
    """Stashes the in-flight request in a thread-local so AuditableModel
    can attribute automatic audit entries to the acting user without every
    view/service having to pass `user=` explicitly (docs/PHASE_6_PLAN.md
    Etape 1)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        bind_current_request(request)
        try:
            return self.get_response(request)
        finally:
            clear_current_request()
