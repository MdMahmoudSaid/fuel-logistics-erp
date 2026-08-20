import threading

_thread_locals = threading.local()


def bind_current_request(request) -> None:
    _thread_locals.request = request


def clear_current_request() -> None:
    _thread_locals.request = None


def get_current_user():
    """The user driving the in-flight HTTP request, if any
    (docs/PHASE_6_PLAN.md Etape 1).

    Reads `request.user` lazily rather than snapshotting it at middleware
    entry: DRF/JWT authentication runs inside the view (APIView.dispatch,
    called from deep within get_response()), after Django's own middleware
    chain has already started, so the raw request's `.user` is still
    unauthenticated at that point. By storing the request itself and
    reading `.user` only when an audited save()/delete() actually asks for
    it, we always see the DRF-authenticated value.
    """
    request = getattr(_thread_locals, "request", None)
    if request is None:
        return None
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user
