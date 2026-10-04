"""
Tests for backend.services.document_memory_service — Chat-R10's get_full_text
(preview/download), added alongside the pre-existing store_document/get_context
(Chat-R6a), which had no direct unit tests before this file.
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.schema import ALL_TABLES
from backend.services import document_memory_service


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


@pytest.fixture(autouse=True)
def fake_embeddings():
    # store_document embeds in batches (Chat-R19b) — stub it so tests don't
    # hit the real API. One fake embedding per input chunk, same shape
    # get_embeddings_batch's real return value has (order-preserving list).
    def _fake_batch(chunks):
        return [[0.0] * 3072 for _ in chunks]
    with patch.object(document_memory_service, "get_embeddings_batch", side_effect=_fake_batch), \
         patch.object(document_memory_service, "get_embedding", return_value=[0.0] * 3072):
        yield


class TestGetFullText:
    def test_returns_none_for_unknown_attachment(self, mem_db):
        assert document_memory_service.get_full_text("does-not-exist") is None

    def test_returns_full_text_single_chunk(self, mem_db):
        attachment_id = document_memory_service.store_document("notes.txt", "Hello world.")
        assert document_memory_service.get_full_text(attachment_id) == "Hello world."

    def test_rejoins_multiple_chunks_in_reading_order(self, mem_db):
        # Force multiple chunks by exceeding _CHUNK_CHARS with distinct paragraphs.
        paragraphs = [f"Paragraph {i} " + ("x" * 200) for i in range(6)]
        text = "\n\n".join(paragraphs)
        attachment_id = document_memory_service.store_document("big.txt", text)

        full = document_memory_service.get_full_text(attachment_id)

        assert full is not None
        assert full.index("Paragraph 0") < full.index("Paragraph 1") < full.index("Paragraph 5")

    def test_not_trimmed_by_token_budget_unlike_get_context(self, mem_db):
        # get_context caps at token_budget; get_full_text must not.
        big_text = "word " * 100_000  # comfortably over get_context's 100K-token default
        attachment_id = document_memory_service.store_document("huge.txt", big_text)

        full = document_memory_service.get_full_text(attachment_id)

        assert full is not None
        assert len(full) >= len(big_text) - 10  # rejoin adds separators, not much loss


class TestGetContext:
    def test_short_paper_sent_in_full_by_default(self, mem_db):
        # Regression: a 5-page paper (~29K chars, ~7.2K tokens — the real
        # ARIIA-2026 docx) blew the old 3000-token default and only 5 of its
        # chunks (~10% of the text) reached the model.
        paragraphs = [f"Section {i}. " + ("detail " * 90) for i in range(45)]
        text = "\n\n".join(paragraphs)
        attachment_id = document_memory_service.store_document("paper.docx", text)

        note = document_memory_service.get_context(attachment_id, "paper.docx", "What is this?")

        assert note.startswith("[Document 'paper.docx', full text:]")
        assert "Section 0." in note and "Section 44." in note

    def test_excerpts_fill_the_budget_not_just_top_five(self, mem_db):
        paragraphs = [f"Chunk {i}. " + ("y" * 780) for i in range(20)]  # one ~200-token chunk each
        attachment_id = document_memory_service.store_document("big.txt", "\n\n".join(paragraphs))
        chunks = document_memory_service._all_chunks(attachment_id)
        ranked = list(reversed(chunks))  # most relevant = last chunk

        with patch.object(document_memory_service, "_search_chunks", return_value=ranked):
            note = document_memory_service.get_context(attachment_id, "big.txt", "q", token_budget=2000)

        # 197 tokens/chunk -> 10 fit in 2000 (the old code stopped at 5)
        assert "showing the 10 most relevant excerpts out of 20" in note
        assert "Chunk 19." in note and "Chunk 10." in note and "Chunk 9." not in note
        assert note.index("Chunk 10.") < note.index("Chunk 19.")  # restored to reading order


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
