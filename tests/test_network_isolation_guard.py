"""The guard that stops pytest from reaching a real provider.

Non-integration tests must never call Gemini, Groq, OpenRouter or TinyFish:
real calls cost quota, make the suite flaky, and write fake production-looking
rows into llm_call_log (649 of them before this guard landed). Constructing a
client stays legal - only sending a request is blocked.
"""
from __future__ import annotations

import httpx
import pytest
import requests

from tests.conftest import RealNetworkCallBlocked, blocked_host


class TestBlockedHostMatching:
    @pytest.mark.parametrize("url", [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent",
        "https://api.groq.com/openai/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
        "https://api.search.tinyfish.ai/search",
    ])
    def test_provider_urls_are_matched(self, url):
        assert blocked_host(url) is not None

    def test_unrelated_url_is_not_matched(self):
        assert blocked_host("https://example.com/anything") is None


class TestGuardBlocksRealRequests:
    def test_httpx_request_to_groq_is_blocked(self):
        with pytest.raises(RealNetworkCallBlocked):
            httpx.Client().get("https://api.groq.com/openai/v1/models")

    def test_requests_call_to_tinyfish_is_blocked(self):
        with pytest.raises(RealNetworkCallBlocked):
            requests.get("https://api.search.tinyfish.ai/search", timeout=5)

    def test_building_a_client_is_still_allowed(self):
        from langchain_groq import ChatGroq
        model = ChatGroq(model="openai/gpt-oss-20b", api_key="test-key")
        assert model.model_name == "openai/gpt-oss-20b"

    def test_invoking_a_model_is_blocked(self):
        from langchain_groq import ChatGroq
        model = ChatGroq(model="openai/gpt-oss-20b", api_key="test-key", max_retries=0)
        with pytest.raises(Exception) as exc_info:
            model.invoke("hi")
        assert "isolation guard" in str(exc_info.value)
