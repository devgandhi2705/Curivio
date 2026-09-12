"""
Shared pytest fixtures for all test modules.
"""

import sqlite3

import pytest
import sqlite_vec

# Test fixtures across the suite create raw sqlite3.connect(":memory:") connections
# and replay ALL_TABLES directly, bypassing backend.utils.db.get_connection() (which
# always loads the sqlite_vec extension per-connection). Since ALL_TABLES now includes
# a CREATE VIRTUAL TABLE ... USING vec0 statement (Chat-3), any raw connection that
# skips loading the extension fails with "no such module: vec0". Patching
# sqlite3.connect here — once — makes every test connection match real production
# connections instead of updating the same fixture in 17 separate test files.
_real_connect = sqlite3.connect


def _connect_with_vec(*args, **kwargs):
    conn = _real_connect(*args, **kwargs)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


sqlite3.connect = _connect_with_vec


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Clear slowapi's in-memory rate-limit counters before every test so that
    tests cannot hit limits set for production (e.g. 10/minute).
    """
    from backend.main import limiter
    limiter._storage.reset()
    yield


# -- Network isolation --------------------------------------------------------
# Every provider SDK in this stack sends over httpx (google-genai, groq,
# openrouter, openai) except TinyFish, which uses requests. Patching the two
# transport entry points covers all of them without knowing each SDK's shape,
# and leaves client construction untouched - offline tests that build a model
# and never call it keep working.
from urllib.parse import urlparse

_BLOCKED_HOSTS = (
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "openrouter.ai",
    "tinyfish.ai",
)


class RealNetworkCallBlocked(RuntimeError):
    """A non-integration test tried to call a real provider."""


def blocked_host(url) -> str | None:
    """The blocked host this URL belongs to, or None. Accepts str or httpx.URL."""
    host = getattr(url, "host", None) or urlparse(str(url)).hostname or ""
    return next((h for h in _BLOCKED_HOSTS if host == h or host.endswith("." + h)), None)


@pytest.fixture(autouse=True)
def block_provider_network(request, monkeypatch):
    """Raise instead of sending a request to a provider, unless the test is
    marked `integration` (those are excluded by pytest.ini's default addopts
    and are the only tests allowed to spend real quota)."""
    if request.node.get_closest_marker("integration"):
        yield
        return

    import httpx
    import requests as _requests

    def _raise_if_blocked(url):
        host = blocked_host(url)
        if host:
            raise RealNetworkCallBlocked(
                f"Real request to {host} blocked by the test isolation guard. "
                "Mock the provider call, or mark the test @pytest.mark.integration."
            )

    def _wrap_send(real_send):
        def _guarded(self, request_obj, *args, **kwargs):
            _raise_if_blocked(getattr(request_obj, "url", ""))
            return real_send(self, request_obj, *args, **kwargs)
        return _guarded

    # groq/openai-style SDKs (Stainless-generated) call httpx's
    # build_request() then send() from inside a `except Exception as err:
    # raise APIConnectionError(...) from err` block that discards the
    # original message, replacing it with a generic "Connection error." -
    # raising in send() alone would still block the call but the guard's
    # own message would never surface. build_request() runs before that
    # try/except, so patching it too keeps the message intact for callers
    # built that way while send() still catches anything constructed and
    # sent without going through build_request() first.
    def _wrap_build_request(real_build_request):
        def _guarded(self, method, url, *args, **kwargs):
            _raise_if_blocked(url)
            return real_build_request(self, method, url, *args, **kwargs)
        return _guarded

    monkeypatch.setattr(httpx.Client, "send", _wrap_send(httpx.Client.send))
    monkeypatch.setattr(httpx.AsyncClient, "send", _wrap_send(httpx.AsyncClient.send))
    monkeypatch.setattr(httpx.Client, "build_request", _wrap_build_request(httpx.Client.build_request))
    monkeypatch.setattr(httpx.AsyncClient, "build_request", _wrap_build_request(httpx.AsyncClient.build_request))
    monkeypatch.setattr(_requests.Session, "send", _wrap_send(_requests.Session.send))
    yield
