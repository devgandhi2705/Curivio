"""classify_error is the only place a provider error gets a name, so it is
tested against the real exception classes with real logged message text.
Counts from llm_call_log since 2026-08-01: 640 Gemini 429s, 467 OpenRouter
402s, 79 Groq TPM 429s, 136 Groq 404s, 53 Gemini ConnectErrors, 21 Gemini 503s."""
from __future__ import annotations

from types import SimpleNamespace

import groq
import httpx
import pytest
from google.genai import errors as genai_errors
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from openrouter import errors as openrouter_errors

from backend.llm import rate_limits


@pytest.fixture(autouse=True)
def _clean_skips():
    rate_limits.clear()
    yield
    rate_limits.clear()


def _groq_error(cls, status, message):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=request), body=None)


def _gemini_quota(quota_id):
    return genai_errors.ClientError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "details": [{"violations": [{"quotaId": quota_id, "quotaValue": "20"}]}],
    }})


def _wrapped(inner, message):
    try:
        raise ChatGoogleGenerativeAIError(message) from inner
    except ChatGoogleGenerativeAIError as exc:
        return exc


class TestClassifyError:
    def test_gemini_daily_quota(self):
        assert rate_limits.classify_error(
            _gemini_quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier")) == "daily_quota"

    def test_gemini_per_minute_quota(self):
        assert rate_limits.classify_error(
            _gemini_quota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")) == "rate_limit"

    def test_gemini_daily_quota_through_the_langchain_wrapper(self):
        wrapped = _wrapped(_gemini_quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
                           "Error calling model (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED.")
        assert rate_limits.classify_error(wrapped) == "daily_quota"

    def test_groq_tokens_per_minute(self):
        exc = _groq_error(groq.RateLimitError, 429, (
            "Error code: 429 - Rate limit reached for model openai/gpt-oss-20b on tokens per "
            "minute (TPM): Limit 8000, Used 6451, Requested 1588. Please try again in 292.5ms."))
        assert rate_limits.classify_error(exc) == "rate_limit"

    def test_groq_requests_per_day(self):
        exc = _groq_error(groq.RateLimitError, 429, (
            "Error code: 429 - Rate limit reached for model openai/gpt-oss-120b on requests "
            "per day (RPD): Limit 1000, Used 1000."))
        assert rate_limits.classify_error(exc) == "daily_quota"

    def test_openrouter_no_credit(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        exc = openrouter_errors.PaymentRequiredResponseError(
            data=SimpleNamespace(error=SimpleNamespace(message=(
                "This request requires more credits, or fewer max_tokens. You requested up to "
                "8192 tokens, but can only afford 183."))),
            raw_response=httpx.Response(402, request=request),
        )
        assert rate_limits.classify_error(exc) == "no_credit"

    def test_gemini_503_is_transient(self):
        exc = genai_errors.ServerError(503, {"error": {
            "code": 503, "status": "UNAVAILABLE",
            "message": "This model is currently experiencing high demand."}})
        assert rate_limits.classify_error(exc) == "transient"

    @pytest.mark.parametrize("exc", [
        httpx.ReadTimeout("The read operation timed out"),
        httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
        groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com/x")),
    ])
    def test_network_failures_are_transient(self, exc):
        assert rate_limits.classify_error(exc) == "transient"

    @pytest.mark.parametrize("status,cls,message", [
        (404, groq.NotFoundError, "Error code: 404 - The model does not exist, code model_not_found"),
        (400, groq.BadRequestError, "Error code: 400 - Tool choice is required, but model did not call a tool"),
        (401, groq.AuthenticationError, "Error code: 401 - Invalid API Key, code invalid_api_key"),
    ])
    def test_client_errors_are_fatal(self, status, cls, message):
        assert rate_limits.classify_error(_groq_error(cls, status, message)) == "fatal"

    def test_our_own_errors_carry_their_own_kind(self):
        from backend.llm.model_provider import InvalidOutputError, PromptTooLargeError
        assert rate_limits.classify_error(InvalidOutputError("no json")) == "invalid_output"
        assert rate_limits.classify_error(PromptTooLargeError("9000 > 7000")) == "budget"


class TestSkipTable:
    def test_unknown_leg_is_not_skipped(self):
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) is None

    def test_rate_limit_parks_only_that_model_and_key(self):
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "rate_limit")
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) == "rate_limit"
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 1) is None
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-20b", 0) is None

    def test_no_credit_parks_the_whole_provider(self):
        rate_limits.record_failure("openrouter", "z-ai/glm-5.3-flash", 0, "no_credit")
        assert rate_limits.is_skipped("openrouter", "z-ai/glm-5.3-flash", 1) == "no_credit"
        assert rate_limits.is_skipped("openrouter", "any/other-model", 0) == "no_credit"
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) is None

    def test_transient_and_fatal_park_nothing(self):
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "transient")
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "fatal")
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) is None

    def test_skip_expires(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(rate_limits, "_now", lambda: now[0])
        rate_limits.record_failure("gemini", "gemini-2.5-flash", 0, "rate_limit")
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) == "rate_limit"
        now[0] += 31          # skip_after_rate_limit_sec = 30
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) is None

    def test_daily_quota_parks_for_an_hour(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(rate_limits, "_now", lambda: now[0])
        rate_limits.record_failure("gemini", "gemini-2.5-flash", 0, "daily_quota")
        now[0] += 120
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) == "daily_quota"
        now[0] += 3600
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) is None
