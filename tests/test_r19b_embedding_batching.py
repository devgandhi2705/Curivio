"""
Chat-R19b: real server-side batching for the embedding pipeline.

- backend.llm.embeddings.get_embeddings_batch: wraps embed_documents, shares
  R19a's exact retry decorator (same instance, not a re-declared copy).
- backend.services.document_memory_service.store_document: embeds+inserts in
  groups of _EMBED_BATCH_SIZE chunks — one get_embeddings_batch call (one
  real request) per group instead of R19a's one request per chunk. A failed
  group's chunks are lost together; every already-committed group survives —
  same incremental-persistence philosophy as R19a, now at batch granularity.
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.llm import embeddings
from backend.llm.embeddings import get_embeddings_batch
from backend.services import document_memory_service
from langchain_google_genai._common import GoogleGenerativeAIError


@pytest.fixture
def mem_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in ALL_TABLES:
        conn.execute(stmt)
    conn.commit()

    @contextmanager
    def _get_conn():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(document_memory_service, "get_connection", _get_conn)
    yield conn
    conn.close()


def _paragraphs(n: int) -> str:
    # Each paragraph alone is under _CHUNK_CHARS (800) but any two combined
    # exceed it, so _chunk_text puts exactly one paragraph per chunk.
    return "\n\n".join(f"Paragraph {i} " + ("x" * 500) for i in range(n))


class TestEmbeddingsBatchSharesRetryDecorator:
    def test_same_retry_policy_objects_as_get_embedding(self):
        # "Reuse R19a's existing tenacity retry decorator" — both functions
        # are wrapped by tenacity's own separate Retrying instance (each
        # needs independent per-call retry state, so those can't be the same
        # object), but both instances hold the identical stop/wait/retry-
        # predicate objects because they came from ONE @_embedding_retry
        # decorator variable, not two re-declared copies of the same config.
        a, b = embeddings.get_embedding.retry, embeddings.get_embeddings_batch.retry
        assert a.stop is b.stop
        assert a.wait is b.wait
        assert a.retry is b.retry

    def test_retries_once_on_transient_error_then_succeeds(self):
        fake_model = MagicMock()
        fake_model.embed_documents.side_effect = [
            GoogleGenerativeAIError("Server disconnected without sending a response."),
            [[0.1, 0.2], [0.3, 0.4]],
        ]
        with patch.object(embeddings, "get_embedding_model", return_value=fake_model):
            result = get_embeddings_batch(["chunk a", "chunk b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        assert fake_model.embed_documents.call_count == 2

    def test_exhausts_retries_and_reraises_real_exception(self):
        fake_model = MagicMock()
        fake_model.embed_documents.side_effect = GoogleGenerativeAIError("still down")
        with patch.object(embeddings, "get_embedding_model", return_value=fake_model):
            with pytest.raises(GoogleGenerativeAIError):
                get_embeddings_batch(["chunk a"])
        assert fake_model.embed_documents.call_count == 3  # stop_after_attempt(3)

    def test_calls_embed_documents_with_batch_size_matching_input(self):
        fake_model = MagicMock()
        fake_model.embed_documents.return_value = [[0.0] * 3] * 5
        chunks = [f"chunk {i}" for i in range(5)]
        with patch.object(embeddings, "get_embedding_model", return_value=fake_model):
            get_embeddings_batch(chunks)
        fake_model.embed_documents.assert_called_once_with(chunks, batch_size=5)


class TestStoreDocumentRequestCount:
    def test_request_count_matches_ceil_chunks_over_batch_size(self, mem_db):
        # 63 chunks at _EMBED_BATCH_SIZE=25 -> 3 batches (25, 25, 13), i.e.
        # 3 real requests instead of 63 — the whole point of R19b.
        text = _paragraphs(63)
        calls = []
        def _fake_batch(chunks):
            calls.append(len(chunks))
            return [[0.0] * 3072 for _ in chunks]
        with patch.object(document_memory_service, "get_embeddings_batch", side_effect=_fake_batch):
            document_memory_service.store_document("big.txt", text)

        assert len(calls) == 3  # request count, not chunk count
        assert calls == [25, 25, 13]


class TestStoreDocumentBatchDurability:
    def test_failure_in_second_batch_preserves_first_batch_only(self, mem_db):
        # 30 chunks -> batch1=[0:25] (succeeds), batch2=[25:30] (fails).
        text = _paragraphs(30)

        def _fake_batch(chunks):
            if len(chunks) == 25:
                return [[0.0] * 3072 for _ in chunks]
            raise RuntimeError("second batch's embedding call failed")

        with patch.object(document_memory_service, "get_embeddings_batch", side_effect=_fake_batch):
            with pytest.raises(RuntimeError):
                document_memory_service.store_document("big.txt", text)

        rows = mem_db.execute(
            "SELECT chunk_index FROM document_chunks_vec WHERE filename = 'big.txt' "
            "ORDER BY CAST(chunk_index AS INTEGER)"
        ).fetchall()
        # First batch (chunks 0-24) committed and durable; second batch
        # (chunks 25-29) never inserted — lost together, not partially.
        assert [r["chunk_index"] for r in rows] == [str(i) for i in range(25)]

    def test_normal_completion_stores_every_chunk_across_multiple_batches(self, mem_db):
        text = _paragraphs(30)
        with patch.object(document_memory_service, "get_embeddings_batch",
                           side_effect=lambda chunks: [[0.0] * 3072 for _ in chunks]):
            attachment_id = document_memory_service.store_document("ok.txt", text)

        rows = mem_db.execute(
            "SELECT chunk_index FROM document_chunks_vec WHERE attachment_id = ? "
            "ORDER BY CAST(chunk_index AS INTEGER)",
            (attachment_id,),
        ).fetchall()
        assert [r["chunk_index"] for r in rows] == [str(i) for i in range(30)]

    def test_small_document_under_one_batch_unaffected(self, mem_db):
        # Well under _EMBED_BATCH_SIZE=25 — single batch, same end behavior
        # as before batching existed.
        with patch.object(document_memory_service, "get_embeddings_batch",
                           side_effect=lambda chunks: [[0.0] * 3072 for _ in chunks]) as mock_batch:
            attachment_id = document_memory_service.store_document("notes.txt", "Hello world.")

        mock_batch.assert_called_once_with(["Hello world."])
        full = document_memory_service.get_full_text(attachment_id)
        assert full == "Hello world."


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
