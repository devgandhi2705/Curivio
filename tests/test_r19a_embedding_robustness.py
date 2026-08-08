"""
Chat-R19a: embedding pipeline robustness fixes.

- backend.llm.embeddings: cached client (no fresh construction per call),
  bounded retry-with-backoff on GoogleGenerativeAIError.
- backend.main's document upload branch: store_document failures surface as
  a clean 502, matching the image branch's existing shape — no raw 500.

store_document's own incremental-persistence behavior (originally per-chunk
here) moved to batch granularity in Chat-R19b — see
test_r19b_embedding_batching.py for those tests; the per-chunk claim this
file used to test is no longer what the code does.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.llm import embeddings
from backend.llm.embeddings import get_embedding, get_embedding_model
from langchain_google_genai._common import GoogleGenerativeAIError


class TestEmbeddingClientCaching:
    def test_get_embedding_model_returns_same_instance_across_calls(self):
        get_embedding_model.cache_clear()
        try:
            a = get_embedding_model()
            b = get_embedding_model()
            assert a is b
        finally:
            get_embedding_model.cache_clear()


class TestEmbeddingRetry:
    def test_retries_once_on_transient_error_then_succeeds(self):
        fake_model = MagicMock()
        fake_model.embed_query.side_effect = [
            GoogleGenerativeAIError("Server disconnected without sending a response."),
            [0.1, 0.2, 0.3],
        ]
        with patch.object(embeddings, "get_embedding_model", return_value=fake_model):
            result = get_embedding("some chunk text")

        assert result == [0.1, 0.2, 0.3]
        assert fake_model.embed_query.call_count == 2

    def test_exhausts_retries_and_reraises_real_exception(self):
        fake_model = MagicMock()
        fake_model.embed_query.side_effect = GoogleGenerativeAIError("still down")
        with patch.object(embeddings, "get_embedding_model", return_value=fake_model):
            with pytest.raises(GoogleGenerativeAIError):
                get_embedding("some chunk text")

        assert fake_model.embed_query.call_count == 3  # stop_after_attempt(3)

    def test_non_matching_exception_not_retried(self):
        fake_model = MagicMock()
        fake_model.embed_query.side_effect = ValueError("unrelated bug")
        with patch.object(embeddings, "get_embedding_model", return_value=fake_model):
            with pytest.raises(ValueError):
                get_embedding("some chunk text")

        assert fake_model.embed_query.call_count == 1  # no retry for non-transient errors


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app, get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "test-user", "email": "user@example.com",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestUploadDocumentErrorHandling:
    def test_store_document_failure_returns_clean_502_not_500(self, client):
        with patch("backend.services.document_memory_service.store_document",
                    side_effect=RuntimeError("embedding pipeline exhausted retries")):
            resp = client.post(
                "/chat/upload",
                files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
            )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "Upload failed — please try again."


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
