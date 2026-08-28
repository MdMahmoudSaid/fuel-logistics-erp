import threading

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

_thread_locals = threading.local()
_jwt_authenticator = JWTAuthentication()


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
    it, we always see the DRF-authenticated value - in theory.

    In practice `request.user` here is Django's own attribute, set by
    django.contrib.auth.middleware.AuthenticationMiddleware from the
    session cookie - it is a *different* object from the `user` DRF's
    JWTAuthentication attaches to the `rest_framework.request.Request`
    wrapper it builds inside APIView.dispatch(). Since this app authenticates
    every API call with a JWT bearer token, not a session cookie (see
    REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] in
    config/settings/base.py), `request.user` was always AnonymousUser and
    every audit log got `user=None` - the "Journal d'audit" bug where the
    "Utilisateur" column only ever showed "—" (UI pass 2026-08-27). Falling
    back to decoding the same bearer token ourselves recovers the actual
    actor without needing access to DRF's wrapped request object.
    """
    request = getattr(_thread_locals, "request", None)
    if request is None:
        return None
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    try:
        result = _jwt_authenticator.authenticate(request)
    except (InvalidToken, AuthenticationFailed):
        return None
    if result is None:
        return None
    jwt_user, _token = result
    return jwt_user
