"""
TinyFish search cache (search_cache_service) wiring.

Covers the branches added when the Tavily removal left retrieval uncached:
cache key shape, hit path skipping the network, empty results not being cached,
and a broken cache degrading to a live call rather than failing the search.

The cache functions are faked at their source module (search_cache_service) —
tinyfish_service imports them inside _cache_get/_cache_put at call time, so the
source module is the correct patch point. No DB needed.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import tinyfish_service as tf


class _FakeResponse:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": self._results}


def _result(url="https://example.com/a", title="A", snippet="body text"):
    return {"title": title, "url": url, "snippet": snippet}


@pytest.fixture
def store(monkeypatch):
    """Dict-backed stand-in for the SQLite search cache."""
    data: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        "backend.services.search_cache_service.get_cached_search",
        lambda key: data.get(key),
    )
    monkeypatch.setattr(
        "backend.services.search_cache_service.cache_search",
        lambda key, results: data.__setitem__(key, results),
    )
    monkeypatch.setattr(tf, "_MOCK", False)
    monkeypatch.setattr(tf, "_API_KEY", "test-key")
    return data


def test_miss_calls_api_then_caches(store):
    with patch.object(tf.requests, "get", return_value=_FakeResponse([_result()])) as get, \
         patch.object(tf, "_log_raw"):
        out = tf.search("vector databases")
    assert get.call_count == 1
    assert [a["url"] for a in out] == ["https://example.com/a"]
    assert store["tinyfish_search:vector databases"] == out


def test_hit_skips_the_network(store):
    with patch.object(tf.requests, "get", return_value=_FakeResponse([_result()])) as get, \
         patch.object(tf, "_log_raw"):
        first = tf.search("vector databases")
        second = tf.search("vector databases")
    assert get.call_count == 1, "second call should have been served from cache"
    assert second == first


def test_include_domains_keyed_separately(store):
    """A domain-scoped search must not collide with the same bare query."""
    with patch.object(tf.requests, "get", return_value=_FakeResponse([_result()])) as get, \
         patch.object(tf, "_log_raw"):
        tf.search("rag")
        tf.search("rag", include_domains=["arxiv.org"])
    assert get.call_count == 2
    assert set(store) == {
        "tinyfish_search:rag",
        "tinyfish_search:rag (site:arxiv.org)",
    }


def test_empty_result_is_not_cached(store):
    """A transient empty response must not pin an empty answer for the whole TTL."""
    with patch.object(tf.requests, "get", return_value=_FakeResponse([])) as get, \
         patch.object(tf, "_log_raw"):
        assert tf.search("nothing here") == []
        assert tf.search("nothing here") == []
    assert store == {}
    assert get.call_count == 2, "an uncached empty must be retried live"


def test_broken_cache_degrades_to_live_call(monkeypatch):
    """Retrieval is a live user path — a cache failure must not fail the search."""
    monkeypatch.setattr(tf, "_MOCK", False)
    monkeypatch.setattr(tf, "_API_KEY", "test-key")

    def boom(*_args, **_kwargs):
        raise RuntimeError("no such table: search_cache")

    monkeypatch.setattr("backend.services.search_cache_service.get_cached_search", boom)
    monkeypatch.setattr("backend.services.search_cache_service.cache_search", boom)

    with patch.object(tf.requests, "get", return_value=_FakeResponse([_result()])), \
         patch.object(tf, "_log_raw"):
        out = tf.search("still works")
    assert [a["url"] for a in out] == ["https://example.com/a"]


def test_mock_mode_bypasses_cache_entirely(monkeypatch, store):
    monkeypatch.setattr(tf, "_MOCK", True)
    with patch.object(tf.requests, "get") as get:
        out = tf.search("anything")
    get.assert_not_called()
    assert out and out[0]["source_op"] == "tinyfish_search"
    assert store == {}, "mock results must never enter the real cache"
