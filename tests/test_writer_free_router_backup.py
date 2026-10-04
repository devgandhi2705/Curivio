"""route_writer_call: Gemini, Groq on quota, and the free router when neither can answer."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services import writer_provider_router as w


def _model(answer=None, error=None):
    model = MagicMock()
    if error:
        model.invoke.side_effect = error
    else:
        model.invoke.return_value = MagicMock(content=answer)
    return model


def _factory(by_legs):
    return lambda legs="all", **kw: by_legs[legs]


def test_non_quota_gemini_error_goes_to_the_free_router():
    legs = {"gemini": _model(error=RuntimeError("500 internal")), "openrouter": _model("{}")}
    with patch("backend.llm.get_chat_model", side_effect=_factory(legs)):
        assert w.route_writer_call("g", "q", "feed_writer") == ("{}", "openrouter")
    assert legs["openrouter"].invoke.call_args.args[0] == "q"     # the compressed prompt


def test_groq_preflight_refusal_goes_to_the_free_router():
    legs = {"gemini": _model(error=RuntimeError("429 RESOURCE_EXHAUSTED")), "groq": _model("never"),
            "openrouter": _model("{}")}
    with patch("backend.llm.get_chat_model", side_effect=_factory(legs)), \
         patch("backend.services.grok_service._preflight_check", side_effect=RuntimeError("too big")):
        assert w.route_writer_call("g", "q", "feed_writer") == ("{}", "openrouter")
    legs["groq"].invoke.assert_not_called()


def test_free_router_failing_too_raises_the_original_error():
    legs = {"gemini": _model(error=RuntimeError("500 internal")),
            "openrouter": _model(error=RuntimeError("router down"))}
    with patch("backend.llm.get_chat_model", side_effect=_factory(legs)):
        with pytest.raises(RuntimeError, match="500 internal"):
            w.route_writer_call("g", "q", "feed_writer")
