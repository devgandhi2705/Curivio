"""
Shared pytest fixtures for all test modules.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Clear slowapi's in-memory rate-limit counters before every test so that
    tests cannot hit limits set for production (e.g. 10/minute).
    """
    from backend.main import limiter
    limiter._storage.reset()
    yield
