"""
Chat-R2: CodeExecutionToolMiddleware must gate code_execution + the
tool_config.include_server_side_tool_invocations override to Gemini 3+ legs
only — gemini-2.5-flash 400s on the combination even with the flag set (a
hard Gemini-generation gate, confirmed live and in Google's own docs), so
applying it unconditionally burned every tool-enabled turn on 6 guaranteed-
fail retries before falling through to the one leg that accepts it.

Unit-tests wrap_model_call() directly with a minimal fake request/handler —
no live API calls, no LangChain dataclass construction (ModelRequest needs a
real AgentState/Runtime we don't have in a unit test; we only touch
.model/.tools/.model_settings/.override(), so a duck-typed fake is enough
and doesn't couple this test to LangChain's internal dataclass shape).
"""
from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI

from backend.llm.chat_agent import CodeExecutionToolMiddleware


class _FakeRequest:
    def __init__(self, model, tools=None, model_settings=None):
        self.model = model
        self.tools = tools or []
        self.model_settings = model_settings or {}
        self.overridden_with = None

    def override(self, **overrides):
        self.overridden_with = overrides
        return ("OVERRIDDEN", overrides)


def _gemini(model_name: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=model_name, api_key="fake-key-not-called")


def _handler(request):
    return ("PASSTHROUGH", request)


def test_gemini_25_flash_leg_skips_code_execution():
    """The hard-gated generation: no override, request goes through unchanged."""
    req = _FakeRequest(model=_gemini("models/gemini-2.5-flash"), tools=["web_search"])
    mw = CodeExecutionToolMiddleware(enabled=True)

    result = mw.wrap_model_call(req, _handler)

    assert result == ("PASSTHROUGH", req)
    assert req.overridden_with is None
    assert req.tools == ["web_search"]  # untouched — code_execution never appended


def test_gemini_3_leg_gets_code_execution_and_flag():
    """The supported generation: code_execution + the tool_config flag are added."""
    req = _FakeRequest(model=_gemini("models/gemini-3.1-flash-lite"), tools=["web_search"])
    mw = CodeExecutionToolMiddleware(enabled=True)

    mw.wrap_model_call(req, _handler)

    assert req.overridden_with is not None
    assert req.overridden_with["tools"] == ["web_search", {"code_execution": {}}]
    assert req.overridden_with["model_settings"]["tool_config"] == {
        "include_server_side_tool_invocations": True
    }


def test_disabled_middleware_skips_even_gemini_3():
    req = _FakeRequest(model=_gemini("models/gemini-3.1-flash-lite"), tools=["web_search"])
    mw = CodeExecutionToolMiddleware(enabled=False)

    result = mw.wrap_model_call(req, _handler)

    assert result == ("PASSTHROUGH", req)
    assert req.overridden_with is None


def test_non_gemini_model_skips_regardless_of_generation():
    class _NotGemini:
        model = "not-a-gemini-model"

    req = _FakeRequest(model=_NotGemini(), tools=["web_search"])
    mw = CodeExecutionToolMiddleware(enabled=True)

    result = mw.wrap_model_call(req, _handler)

    assert result == ("PASSTHROUGH", req)
    assert req.overridden_with is None


if __name__ == "__main__":
    test_gemini_25_flash_leg_skips_code_execution()
    test_gemini_3_leg_gets_code_execution_and_flag()
    test_disabled_middleware_skips_even_gemini_3()
    test_non_gemini_model_skips_regardless_of_generation()
    print("all CodeExecutionToolMiddleware leg-gating checks passed")
