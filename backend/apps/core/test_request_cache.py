"""Read-only request cache: an identical read computed twice while serving
one GET runs its query once; nothing is cached outside a GET."""

from decimal import Decimal

import pytest
from django.test import RequestFactory

from apps.core.middleware import ReadOnlyRequestCacheMiddleware
from apps.core.request_cache import memoize_per_request, read_cache

calls = []


@memoize_per_request
def _count_call(key, factor=1):
    calls.append((key, factor))
    return {"value": Decimal(key) * factor}


class _FakeModel:
    class _meta:
        label = "tests.fake"

    def __init__(self, pk):
        self.pk = pk


@memoize_per_request
def _for_instance(instance):
    calls.append(instance.pk)
    return instance.pk


@pytest.fixture(autouse=True)
def _reset():
    calls.clear()


def test_outside_a_read_cache_every_call_runs():
    _count_call(1)
    _count_call(1)
    assert len(calls) == 2


def test_inside_a_read_cache_identical_calls_run_once():
    with read_cache():
        assert _count_call(1) == {"value": Decimal("1")}
        assert _count_call(1) == {"value": Decimal("1")}
        _count_call(1, factor=2)
    assert calls == [(1, 1), (1, 2)]


def test_cached_results_are_copies_the_caller_cannot_corrupt():
    with read_cache():
        _count_call(3)["value"] = "corrupted"
        assert _count_call(3) == {"value": Decimal("3")}


def test_model_instances_are_keyed_by_pk_and_unsaved_ones_are_not_cached():
    with read_cache():
        _for_instance(_FakeModel(5))
        _for_instance(_FakeModel(5))
        _for_instance(_FakeModel(None))
        _for_instance(_FakeModel(None))
    assert calls == [5, None, None]


def test_cache_is_dropped_when_the_block_ends():
    with read_cache():
        _count_call(4)
    with read_cache():
        _count_call(4)
    assert len(calls) == 2


def test_primed_value_is_served_without_running_the_function():
    with read_cache():
        _count_call.prime({"value": Decimal("99")}, 8)
        assert _count_call(8) == {"value": Decimal("99")}
    assert calls == []


def test_priming_outside_a_read_cache_is_ignored():
    _count_call.prime({"value": Decimal("99")}, 8)
    assert _count_call(8) == {"value": Decimal("8")}


def test_is_cached_reports_only_values_known_in_this_request():
    assert _count_call.is_cached(9) is False
    with read_cache():
        assert _count_call.is_cached(9) is False
        _count_call(9)
        assert _count_call.is_cached(9) is True
        _count_call.prime({"value": Decimal("1")}, 10)
        assert _count_call.is_cached(10) is True
    assert _count_call.is_cached(9) is False


def _middleware_calls(method):
    def view(request):
        _count_call(7)
        _count_call(7)
        return None

    middleware = ReadOnlyRequestCacheMiddleware(view)
    middleware(getattr(RequestFactory(), method)("/api/anything/"))
    return len(calls)


def test_middleware_caches_reads_of_a_get_request():
    assert _middleware_calls("get") == 1


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_middleware_never_caches_a_writing_request(method):
    assert _middleware_calls(method) == 2
