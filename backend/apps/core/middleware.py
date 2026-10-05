from apps.core.request_cache import read_cache

_READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}


class ReadOnlyRequestCacheMiddleware:
    """Serves each GET with a fresh per-request cache (apps.core.
    request_cache) so identical reads made while building one page hit the
    database once. Writing requests never get one: a figure read after a
    write in the same request must always see that write."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in _READ_ONLY_METHODS:
            return self.get_response(request)
        with read_cache():
            return self.get_response(request)
