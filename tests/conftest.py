"""
Shared pytest fixtures for all test modules.
"""

import sqlite3
from contextlib import contextmanager

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


# -- llm_call_log isolation (M14) ---------------------------------------------
# The network guard below stops a provider call from succeeding, but every
# writer that logs the resulting failure (LLMCallLogger's callback, and every
# direct write_call_row() caller: tinyfish_service, translate_service,
# tts_service, unpack_service, web_search_reasoning_service, main.py's explain
# logging) still goes through backend.llm.call_logger.write_call_row(), which
# opens its own connection via the module-level get_connection() lazy
# delegate. Left alone, that still lands is_test=0 failure rows in the real
# data/curivio.db. Captured at import time, before any test can monkeypatch
# it, so block_provider_network below can tell "nobody touched
# db.get_connection this test" apart from "a test already pointed it at its
# own connection".
import backend.utils.db as _db_module

_REAL_DB_GET_CONNECTION = _db_module.get_connection


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

    # M14: a blocked provider call above still gets logged — LLMCallLogger's
    # on_llm_error, or a service's own write_call_row(success=False) — and that
    # write must not land in the real data/curivio.db. Both paths share
    # backend.llm.call_logger.write_call_row(), which resolves get_connection()
    # as a module-level name at call time, so patching it here is the one
    # place that covers every writer (see the grep in the review: tinyfish_
    # service, translate_service, tts_service, unpack_service,
    # web_search_reasoning_service, main.py's explain logging, plus the
    # LangChain callback). Guarded rather than unconditional: a test that
    # points backend.utils.db.get_connection at its own connection
    # (test_call_log_route.py's `db` fixture) still reaches that connection —
    # this only redirects the default case nobody isolated themselves.
    import backend.llm.call_logger as call_logger
    from backend.database.schema import ALL_TABLES, MIGRATIONS

    _lazy_conn: list[sqlite3.Connection] = []

    def _throwaway_connection() -> sqlite3.Connection:
        if not _lazy_conn:
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            for statement in ALL_TABLES:
                conn.execute(statement)
            for migration in MIGRATIONS:
                for stmt in migration if isinstance(migration, (list, tuple)) else [migration]:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError:
                        pass  # additive migration already applied by ALL_TABLES — expected
            conn.commit()
            _lazy_conn.append(conn)
        return _lazy_conn[0]

    @contextmanager
    def _throwaway_get_connection():
        conn = _throwaway_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _guarded_get_connection():
        if _db_module.get_connection is _REAL_DB_GET_CONNECTION:
            return _throwaway_get_connection()
        # A test already pointed backend.utils.db.get_connection at its own
        # connection — respect it, same as call_logger's real lazy delegate would.
        return _db_module.get_connection()

    monkeypatch.setattr(call_logger, "get_connection", _guarded_get_connection)
    yield
