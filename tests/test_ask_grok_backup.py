"""ask_grok is Groq-only; when Groq fails, the OpenRouter free router answers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services import grok_service


def _backup(text="backup answer"):
    model = MagicMock()
    model.invoke.return_value = MagicMock(content=text)
    return model


def test_groq_failure_falls_back_to_the_free_router():
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("429 rate limit")
    backup = _backup()
    with patch.object(grok_service, "_get_client", return_value=client), \
         patch("backend.llm.model_provider.get_chat_model", return_value=backup) as factory:
        assert grok_service.ask_grok("prompt", json_mode=True) == "backup answer"
    factory.assert_called_once_with(legs="openrouter", json_mode=True)


def test_both_failing_still_raises_the_api_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("timeout")
    backup = MagicMock()
    backup.invoke.side_effect = Exception("free router down")
    with patch.object(grok_service, "_get_client", return_value=client), \
         patch("backend.llm.model_provider.get_chat_model", return_value=backup):
        with pytest.raises(RuntimeError, match="API request failed"):
            grok_service.ask_grok("prompt")


def test_prompt_too_big_for_groq_goes_to_the_free_router():
    client = MagicMock()
    with patch.object(grok_service, "_get_client", return_value=client), \
         patch.object(grok_service, "_preflight_check", side_effect=RuntimeError("exceeds effective budget")), \
         patch("backend.llm.model_provider.get_chat_model", return_value=_backup("big answer")):
        assert grok_service.ask_grok("huge prompt") == "big answer"
    client.chat.completions.create.assert_not_called()
