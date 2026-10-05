"""Per-request memoisation of read-only computations.

A page such as the dashboard asks for the same figure many times while it
is built (a trip's transport cost is needed by the margin report, the
profit preview and the stock valuation alike). Inside `read_cache()` a
function decorated with `memoize_per_request` runs its query once per
distinct argument set; outside it - every writing request, every service
call from a command or a test - it behaves exactly as before.

Only decorate functions whose result depends solely on database rows
identified by their arguments (model instances are keyed by their primary
key), never on unsaved in-memory state.
"""

import copy
import functools
from contextlib import contextmanager
from contextvars import ContextVar

_store: ContextVar[dict | None] = ContextVar("read_only_request_cache", default=None)


class _Uncacheable(Exception):
    pass


def _key_part(value):
    if isinstance(value, type):
        return value
    meta = getattr(value, "_meta", None)
    if meta is not None and hasattr(value, "pk"):
        if value.pk is None:
            raise _Uncacheable
        return (meta.label, value.pk)
    if isinstance(value, (list, tuple)):
        return tuple(_key_part(item) for item in value)
    hash(value)  # TypeError for an unhashable argument -> not cached
    return value


@contextmanager
def read_cache():
    token = _store.set({})
    try:
        yield
    finally:
        _store.reset(token)


def memoize_per_request(func):
    def make_key(args, kwargs):
        return (
            func.__module__,
            func.__qualname__,
            tuple(_key_part(arg) for arg in args),
            tuple(sorted((name, _key_part(value)) for name, value in kwargs.items())),
        )

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        store = _store.get()
        if store is None:
            return func(*args, **kwargs)
        try:
            key = make_key(args, kwargs)
        except (_Uncacheable, TypeError):
            return func(*args, **kwargs)
        if key not in store:
            store[key] = func(*args, **kwargs)
        # A copy, so a caller that mutates its result (adds a key to a
        # breakdown dict) never corrupts what the next caller reads.
        return copy.deepcopy(store[key])

    def prime(value, *args, **kwargs):
        """Record `value` as the result for these arguments - lets a list
        page compute a figure for all its rows in one query instead of one
        query per row. A no-op outside a read cache."""
        store = _store.get()
        if store is None:
            return
        try:
            store[make_key(args, kwargs)] = value
        except (_Uncacheable, TypeError):
            pass

    def is_cached(*args, **kwargs):
        store = _store.get()
        if store is None:
            return False
        try:
            return make_key(args, kwargs) in store
        except (_Uncacheable, TypeError):
            return False

    wrapper.prime = prime
    wrapper.is_cached = is_cached
    return wrapper
