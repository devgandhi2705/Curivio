"""Shared text-processing helpers."""

from __future__ import annotations

import re

# Sentence-ending punctuation followed by whitespace or end-of-string —
# same lookahead idiom used by source_intelligence_service._split_sentences,
# avoids false positives on decimals like "3.14" (no whitespace after the dot).
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?](?=\s|$)")


def truncate_at_sentence(text: str, limit: int) -> str:
    """
    Truncate `text` to at most `limit` chars, cutting at the last complete
    sentence ending (. ! ?) at or before the limit instead of mid-word.

    Falls back to a hard cut at `limit` when no sentence boundary exists
    within the window (e.g. one long run-on sentence).
    """
    if len(text) <= limit:
        return text

    window  = text[:limit]
    matches = list(_SENTENCE_BOUNDARY_RE.finditer(window))
    if not matches:
        return window

    cut = matches[-1].end()
    return window[:cut].rstrip()
