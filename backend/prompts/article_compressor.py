"""
ArticleCompressor — progressive article compression for budget-aware prompts.

Phase 3.3 deliverable.

The Problem
-----------
Raw Tavily articles arrive with 1,000–3,000 chars of content each.
Eight articles × 2,000 chars = 16,000 chars ≈ 4,000 tokens — consumed before
a single instruction reaches the model.  With 16 articles (deep research),
that balloons to 8,000 tokens.  On Groq's free tier (12,000 TPM limit) this
is fatal.

The Solution
-----------
Four deterministic compression levels that progressively reduce token usage
while preserving the semantic signals the model actually needs:

  Level 0  FULL     Original content trimmed to MAX_FULL_CHARS (1,200).
                    ~250 tokens/article.  Use when budget is plentiful.

  Level 1  DETAILED Structured fields + first 300-char content snapshot.
                    ~150 tokens/article.  Good default for most prompts.

  Level 2  INSIGHT  Structured fields only — no raw content snippet.
                    ~80 tokens/article.  Use under moderate budget pressure.

  Level 3  CLAIM    One line per article: key claim + URL.
                    ~30 tokens/article.  Use under severe budget pressure.

Structured fields (extracted by signal-based heuristics, no LLM required)
--------------------------------------------------------------------------
  key_claim    Single most important claim or finding.
  evidence     Key supporting data — numbers, study results, named sources.
  implication  What this means for the domain — consequence language.
  novelty      What makes this new — announcement / breakthrough signals.

Compression invariants
----------------------
  1. title  and  url  are ALWAYS preserved at every level.
  2. key_claim is preserved at every level except Level 3 line truncation.
  3. Compression is deterministic — no LLM calls, no randomness.
  4. Empty fields degrade gracefully; no KeyError or AttributeError.

Usage
-----
    from backend.prompts.article_compressor import ArticleCompressor

    compressor  = ArticleCompressor()
    compressed  = compressor.compress_batch(raw_articles)

    # Auto-select level to fit a token budget
    text, meta  = compressor.format_within_budget(compressed, budget_tokens=4_000)

    # Manually pick a level
    text = compressor.format_batch(compressed, level=2)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence


# ── Constants ─────────────────────────────────────────────────────────────────

LEVEL_FULL     = 0   # original content, trimmed to MAX_FULL_CHARS
LEVEL_DETAILED = 1   # structured fields + 300-char content snapshot
LEVEL_INSIGHT  = 2   # structured fields only
LEVEL_CLAIM    = 3   # one line: key claim + URL

LEVEL_NAMES: dict[int, str] = {
    LEVEL_FULL:     "FULL",
    LEVEL_DETAILED: "DETAILED",
    LEVEL_INSIGHT:  "INSIGHT",
    LEVEL_CLAIM:    "CLAIM",
}

LEVEL_DESCRIPTIONS: dict[int, str] = {
    LEVEL_FULL:     "original content trimmed to 1,200 chars (~250 tokens/article)",
    LEVEL_DETAILED: "structured fields + 300-char snapshot (~150 tokens/article)",
    LEVEL_INSIGHT:  "structured fields only (~80 tokens/article)",
    LEVEL_CLAIM:    "one-line key claim + URL (~30 tokens/article)",
}

_MAX_FULL_CHARS:     int = 1_200   # Level 0 content cap
_MIN_SENTENCE_LEN:   int = 20      # discard sub-sentence fragments

# Per-level field character limits — tighter caps at higher compression levels
# ensure the monotonic invariant: len(L0) >= len(L1) >= len(L2) >= len(L3)
_L1_CLAIM_CHARS:    int = 120      # Level 1 key_claim cap
_L1_EVIDENCE_CHARS: int = 100      # Level 1 evidence cap
_L1_SNAPSHOT_CHARS: int = 150      # Level 1 content snapshot

_L2_CLAIM_CHARS:    int = 100      # Level 2 key_claim cap
_L2_EVIDENCE_CHARS: int = 80       # Level 2 evidence cap
_L2_IMPL_CHARS:     int = 80       # Level 2 implication cap
_L2_NOVELTY_CHARS:  int = 80       # Level 2 novelty cap

_MAX_FIELD_CHARS:   int = 220      # extraction buffer — trimmed per-level at format time


# ── Signal patterns for field extraction ──────────────────────────────────────

_EVIDENCE_RE = re.compile(
    r"""
    \d+[%,]          |   # percentages / numbers
    \d+\.\d+         |   # decimal numbers
    billion          |
    million          |
    thousand         |
    percent          |
    study            |
    report           |
    research         |
    survey           |
    analysis         |
    data             |
    according\s+to   |
    found\s+that     |
    shows?\s+that    |
    indicates?       |
    estimated?       |
    measured         |
    recorded
    """,
    re.IGNORECASE | re.VERBOSE,
)

_IMPLICATION_SIGNALS: tuple[str, ...] = (
    "this means", "this could", "this will", "this would", "this enables",
    "as a result", "therefore", "which means", "leading to", "which has",
    "enabling ", "allowing ", "which could", "may affect", "will affect",
    "impact on", "consequence", "implication", "meaning that", "so that",
    "in order to", "this makes", "this allows", "this forces",
)

_NOVELTY_SIGNALS: tuple[str, ...] = (
    "first ", "new ", "breakthrough", "unprecedented", " marks ",
    "launches", "announces", "introduces", "reveals", "discovers",
    "develops new", "record ", "latest ", "emerges", "shifts",
    "for the first", "never before",
)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CompressedArticle:
    """
    A single article compressed at all four levels.

    Fields
    ------
    title, url      Always preserved regardless of level.
    key_claim       Single most important finding.
    evidence        Key supporting data or source citation.
    implication     Domain consequence — what this means.
    novelty         What makes this new or different.
    level0..level3  Pre-built formatted strings for each compression level.
    original_chars  Character count of the original content.
    """

    title:          str
    url:            str
    key_claim:      str
    evidence:       str
    implication:    str
    novelty:        str

    # Pre-built formatted strings — set by ArticleCompressor.compress()
    level0: str = ""
    level1: str = ""
    level2: str = ""
    level3: str = ""

    original_chars: int = 0

    def at_level(self, level: int) -> str:
        """Return the article representation at the given compression level."""
        if level <= LEVEL_FULL:     return self.level0
        if level == LEVEL_DETAILED: return self.level1
        if level == LEVEL_INSIGHT:  return self.level2
        return self.level3

    def tokens_at_level(self, level: int) -> int:
        """Estimated token count at the given level (4-char heuristic)."""
        return max(1, len(self.at_level(level)) // 4)

    @property
    def compression_ratio(self) -> float:
        """Chars saved from Level 0 → Level 2 relative to Level 0."""
        if not self.level0:
            return 0.0
        return 1.0 - (len(self.level2) / len(self.level0))


@dataclass
class CompressionResult:
    """
    Metadata about a format_within_budget() call.

    Describes which compression level was selected and whether the result
    fits within the token budget.
    """
    level:              int
    level_name:         str
    articles_count:     int
    total_tokens:       int
    token_budget:       int
    fits:               bool
    level0_tokens:      int    # tokens at full content (for comparison)
    compression_ratio:  float  # 1 - (total_tokens / level0_tokens)

    def summary(self) -> str:
        saved = self.level0_tokens - self.total_tokens
        pct   = (saved / self.level0_tokens * 100) if self.level0_tokens else 0.0
        status = "OK" if self.fits else "OVER BUDGET"
        return (
            f"Level {self.level} ({self.level_name}) — "
            f"{self.articles_count} articles — "
            f"{self.total_tokens:,} / {self.token_budget:,} tokens — "
            f"saved {saved:,} tok ({pct:.0f}% vs full) — {status}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Core compressor
# ═══════════════════════════════════════════════════════════════════════════════

class ArticleCompressor:
    """
    Compresses raw article dicts into CompressedArticle objects at all four
    levels using deterministic, heuristic signal extraction.

    No LLM calls.  No external dependencies.  Idempotent.
    """

    # ── Single article ────────────────────────────────────────────────────────

    def compress(self, article: dict, index: int = 1) -> CompressedArticle:
        """
        Compress a single article dict into a CompressedArticle.

        Accepts the standard Tavily result shape:
            {"title": "...", "url": "...", "content": "..."}

        index is used for numbered labels in Level 0–2 formats.
        """
        title   = (article.get("title")   or "").strip()
        url     = (article.get("url")     or "").strip()
        content = (article.get("content") or "").strip()

        # Extract structured fields
        key_claim   = _extract_key_claim(title, content)
        evidence    = _extract_evidence(content)
        implication = _extract_implication(content)
        novelty     = _extract_novelty(title, content)

        # Build all four level representations
        level0 = _format_level0(index, title, url, content)
        level1 = _format_level1(index, title, url, key_claim, evidence, content)
        level2 = _format_level2(index, title, url, key_claim, evidence, implication, novelty)
        level3 = _format_level3(index, title, url, key_claim)

        # Enforce monotonic invariant: each level ≤ previous.
        # For very short articles the structured overhead can exceed the raw
        # content; clamp up so the guarantee always holds.
        if len(level1) > len(level0):
            level1 = level0
        if len(level2) > len(level1):
            level2 = level1

        return CompressedArticle(
            title         = title,
            url           = url,
            key_claim     = key_claim,
            evidence      = evidence,
            implication   = implication,
            novelty       = novelty,
            level0        = level0,
            level1        = level1,
            level2        = level2,
            level3        = level3,
            original_chars = len(content),
        )

    def compress_batch(
        self,
        articles: Sequence[dict],
        max_articles: int = 8,
    ) -> list[CompressedArticle]:
        """
        Compress a list of raw article dicts.

        Caps at max_articles to prevent unbounded context growth.
        Returns at most max_articles CompressedArticle objects.
        """
        return [
            self.compress(a, i)
            for i, a in enumerate(articles[:max_articles], start=1)
        ]

    # ── Batch formatting ──────────────────────────────────────────────────────

    def format_batch(
        self,
        compressed: Sequence[CompressedArticle],
        level: int,
    ) -> str:
        """Format a list of compressed articles at a fixed level."""
        if not compressed:
            return "(no articles)"
        return "\n\n".join(a.at_level(level) for a in compressed)

    # ── Budget-aware auto-selection ───────────────────────────────────────────

    def format_within_budget(
        self,
        compressed: Sequence[CompressedArticle],
        budget_tokens: int,
        min_articles: int = 1,
    ) -> tuple[str, CompressionResult]:
        """
        Auto-select the lowest compression level that fits within budget_tokens.

        Tries levels 0 → 3 in order.  If even Level 3 exceeds the budget, returns
        Level 3 with a OVER BUDGET flag in the CompressionResult.

        Parameters
        ----------
        compressed     List of CompressedArticle objects.
        budget_tokens  Maximum tokens allowed for the formatted article block.
        min_articles   If the article list has fewer than min_articles items,
                       the result is returned as-is even if over budget.

        Returns
        -------
        (formatted_text, CompressionResult)
        """
        articles_list = list(compressed)
        level0_tokens = _batch_tokens(articles_list, LEVEL_FULL)

        for level in (LEVEL_FULL, LEVEL_DETAILED, LEVEL_INSIGHT, LEVEL_CLAIM):
            text   = self.format_batch(articles_list, level)
            tokens = max(1, len(text) // 4)
            if tokens <= budget_tokens:
                ratio = 1.0 - (tokens / level0_tokens) if level0_tokens else 0.0
                return text, CompressionResult(
                    level             = level,
                    level_name        = LEVEL_NAMES[level],
                    articles_count    = len(articles_list),
                    total_tokens      = tokens,
                    token_budget      = budget_tokens,
                    fits              = True,
                    level0_tokens     = level0_tokens,
                    compression_ratio = ratio,
                )

        # Even Level 3 doesn't fit — return it with fits=False
        text   = self.format_batch(articles_list, LEVEL_CLAIM)
        tokens = max(1, len(text) // 4)
        ratio  = 1.0 - (tokens / level0_tokens) if level0_tokens else 0.0
        return text, CompressionResult(
            level             = LEVEL_CLAIM,
            level_name        = LEVEL_NAMES[LEVEL_CLAIM],
            articles_count    = len(articles_list),
            total_tokens      = tokens,
            token_budget      = budget_tokens,
            fits              = False,
            level0_tokens     = level0_tokens,
            compression_ratio = ratio,
        )

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def compression_report(
        self,
        compressed: Sequence[CompressedArticle],
    ) -> str:
        """
        Return a formatted token-count comparison across all four levels.

        Example output::

            ArticleCompressor — 8 articles
            Level 0  FULL      2,016 tokens  (  — baseline)
            Level 1  DETAILED  1,200 tokens  ( 40% reduction)
            Level 2  INSIGHT     640 tokens  ( 68% reduction)
            Level 3  CLAIM       232 tokens  ( 88% reduction)
        """
        articles_list = list(compressed)
        if not articles_list:
            return "ArticleCompressor — 0 articles"

        base = _batch_tokens(articles_list, LEVEL_FULL)
        lines = [f"ArticleCompressor — {len(articles_list)} articles"]
        for level in (LEVEL_FULL, LEVEL_DETAILED, LEVEL_INSIGHT, LEVEL_CLAIM):
            tok  = _batch_tokens(articles_list, level)
            pct  = (1.0 - tok / base) * 100 if base else 0.0
            if level == LEVEL_FULL:
                detail = "baseline"
            else:
                detail = f"{pct:.0f}% reduction"
            lines.append(
                f"  Level {level}  {LEVEL_NAMES[level]:<10s}"
                f" {tok:>7,} tokens  ({detail:>14})"
            )
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Field extraction helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, discarding sub-sentence fragments."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if len(s.strip()) >= _MIN_SENTENCE_LEN]


def _extract_key_claim(title: str, content: str) -> str:
    """The single most important claim — typically the opening statement."""
    sentences = _split_sentences(content)
    if sentences:
        return sentences[0][:_MAX_FIELD_CHARS]
    return (title or "")[:_MAX_FIELD_CHARS]


def _extract_evidence(content: str) -> str:
    """Sentences containing quantitative data, studies, or named sources."""
    sentences = _split_sentences(content)
    collected: list[str] = []
    chars = 0
    for s in sentences:
        if _EVIDENCE_RE.search(s):
            collected.append(s)
            chars += len(s)
            if chars >= _MAX_FIELD_CHARS:
                break
    if collected:
        return " ".join(collected)[:_MAX_FIELD_CHARS]
    # Fallback: second sentence (often contains supporting detail)
    return sentences[1][:_MAX_FIELD_CHARS] if len(sentences) > 1 else ""


def _extract_implication(content: str) -> str:
    """Sentences with consequence or causal language."""
    sentences = _split_sentences(content)
    s_lower_list = [(s, s.lower()) for s in sentences]
    for s, sl in s_lower_list:
        if any(sig in sl for sig in _IMPLICATION_SIGNALS):
            return s[:_MAX_FIELD_CHARS]
    # Fallback: last sentence (articles often end with implications)
    return sentences[-1][:_MAX_FIELD_CHARS] if sentences else ""


def _extract_novelty(title: str, content: str) -> str:
    """Sentences or title fragments that signal what's new or different."""
    sentences = _split_sentences(content)
    for s in sentences:
        sl = s.lower()
        if any(sig in sl for sig in _NOVELTY_SIGNALS):
            return s[:_MAX_FIELD_CHARS]
    # Check if title itself carries novelty signals
    if title:
        tl = title.lower()
        if any(sig in tl for sig in _NOVELTY_SIGNALS):
            return title[:_MAX_FIELD_CHARS]
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Level format builders
# ═══════════════════════════════════════════════════════════════════════════════

def _format_level0(index: int, title: str, url: str, content: str) -> str:
    """Level 0 — Full content, trimmed to MAX_FULL_CHARS."""
    trimmed = content[:_MAX_FULL_CHARS].strip()
    return (
        f"[ARTICLE {index}]\n"
        f"Title: {title}\n"
        f"URL:   {url}\n"
        f"Content: {trimmed}"
    )


def _format_level1(
    index: int, title: str, url: str,
    key_claim: str, evidence: str,
    content: str,
) -> str:
    """Level 1 — Key claim + evidence + 150-char snapshot. No implication/novelty."""
    snapshot = content[:_L1_SNAPSHOT_CHARS].strip()
    parts = [
        f"[ARTICLE {index}]",
        f"Title: {title}",
        f"URL:   {url}",
    ]
    if key_claim:
        parts.append(f"Key Claim: {key_claim[:_L1_CLAIM_CHARS]}")
    if evidence:
        parts.append(f"Evidence:  {evidence[:_L1_EVIDENCE_CHARS]}")
    if snapshot:
        parts.append(f"Snapshot:  {snapshot}")
    return "\n".join(parts)


def _format_level2(
    index: int, title: str, url: str,
    key_claim: str, evidence: str, implication: str, novelty: str,
) -> str:
    """Level 2 — All four structured fields with tight char caps, no raw content."""
    parts = [
        f"[A{index}] {title}",
        f"URL: {url}",
    ]
    if key_claim:
        parts.append(f"Claim:       {key_claim[:_L2_CLAIM_CHARS]}")
    if evidence:
        parts.append(f"Evidence:    {evidence[:_L2_EVIDENCE_CHARS]}")
    if implication:
        parts.append(f"Implication: {implication[:_L2_IMPL_CHARS]}")
    if novelty:
        parts.append(f"Novelty:     {novelty[:_L2_NOVELTY_CHARS]}")
    return "\n".join(parts)


def _format_level3(index: int, title: str, url: str, key_claim: str) -> str:
    """Level 3 — One line per article: claim + URL."""
    claim = key_claim or title
    return f"{index}. [{title}] {claim[:120]} ({url})"


# ── Private helpers ────────────────────────────────────────────────────────────

def _batch_tokens(articles: list[CompressedArticle], level: int) -> int:
    """Total estimated tokens for a batch at the given level."""
    text = "\n\n".join(a.at_level(level) for a in articles)
    return max(1, len(text) // 4)
