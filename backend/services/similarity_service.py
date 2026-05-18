"""
Lightweight text similarity utilities for the AI learning agent.

Detects duplicate articles, near-identical learning topics, and repetitive
news summaries — all without external NLP libraries.

Algorithm
---------
Similarity is Jaccard overlap on cleaned word-token sets, with a domain-aware
acronym expansion step that maps AI/ML abbreviations to their full forms before
comparison.  This makes short topic names like "RAG Pipelines" and "Retrieval
Augmented Generation" register as near-identical rather than completely distinct.

Typical token counts after expansion:
  "RAG Pipelines"                       → {retrieval, augmented, generation, pipelines}
  "Retrieval Augmented Generation"      → {retrieval, augmented, generation}
  Jaccard: 3 / 4 = 0.75  → duplicate at TOPIC_SIM_THRESHOLD = 0.50  ✓

  "Fine-tuning LLMs"                    → {fine, tuning, large, language, models}
  "Fine-Tuning Large Language Models"   → {fine, tuning, large, language, models}
  Jaccard: 5 / 5 = 1.0  → duplicate  ✓

Public API
----------
token_overlap(a, b)                              → float  [0, 1] Jaccard
are_duplicate_articles(a, b)                     → bool
deduplicate_articles(articles)                   → list[dict]
find_similar_in(candidate, seen, threshold)      → str | None
deduplicate_topics(topics, threshold)            → list[dict]
is_fresh_summary(new_title, recent, threshold)   → bool
"""

import re
from urllib.parse import urlparse

# ── Tuneable thresholds ───────────────────────────────────────────────────────

# Articles: very conservative — only fire on near-identical titles.
ARTICLE_DUP_THRESHOLD: float = 0.70

# Topics: moderate — catches acronym-synonyms after expansion.
TOPIC_SIM_THRESHOLD: float = 0.50

# Summaries: broader — topic-level freshness check on news titles.
SUMMARY_SIM_THRESHOLD: float = 0.40


# ── Text normalisation ────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of with is are was were be been "
    "being have has had do does did will would could should may might can "
    "this that these those it its from by as about into over after how why "
    "what when where who which".split()
)

_MIN_TOKEN_LEN = 3

# Domain acronym expansions — applied token-by-token before Jaccard comparison.
# Keeping this list conservative; only unambiguous AI/ML abbreviations included.
_ACRONYM_MAP: dict[str, str] = {
    "rag":   "retrieval augmented generation",
    "llm":   "large language model",
    "llms":  "large language models",
    "nlp":   "natural language processing",
    "ml":    "machine learning",
    "dl":    "deep learning",
    "cv":    "computer vision",
    "rl":    "reinforcement learning",
    "gpt":   "generative pretrained transformer",
    "bert":  "bidirectional encoder representations",
    "vae":   "variational autoencoder",
    "gan":   "generative adversarial network",
    "cnn":   "convolutional neural network",
    "rnn":   "recurrent neural network",
    "lstm":  "long short term memory",
    "moe":   "mixture of experts",
    "lora":  "low rank adaptation",
    "rlhf":  "reinforcement learning human feedback",
    "peft":  "parameter efficient fine tuning",
    "sft":   "supervised fine tuning",
    "rag":   "retrieval augmented generation",
    "kv":    "key value",
    "mha":   "multi head attention",
    "mlm":   "masked language model",
    "clm":   "causal language model",
}


def _raw_tokens(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return [w for w in cleaned.split() if len(w) >= _MIN_TOKEN_LEN and w not in _STOP_WORDS]


def _expanded_token_set(text: str) -> frozenset[str]:
    """
    Return a frozenset of tokens after stop-word removal and acronym expansion.

    Each token is checked against _ACRONYM_MAP; if found, it is replaced by
    the expansion tokens (which are then also filtered for stop words and length).
    """
    result: list[str] = []
    for token in _raw_tokens(text):
        expansion = _ACRONYM_MAP.get(token)
        if expansion:
            result.extend(_raw_tokens(expansion))
        else:
            result.append(token)
    return frozenset(result)


# ── Public API ────────────────────────────────────────────────────────────────

def token_overlap(a: str, b: str) -> float:
    """
    Jaccard similarity on acronym-expanded, stop-word-filtered token sets.

    Returns 1.0 when both strings are empty (vacuously identical).
    Returns 0.0 when one string is empty and the other is not.
    """
    tokens_a = _expanded_token_set(a)
    tokens_b = _expanded_token_set(b)

    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = len(tokens_a & tokens_b)
    union        = len(tokens_a | tokens_b)
    return intersection / union


def are_duplicate_articles(a: dict, b: dict) -> bool:
    """
    True when two articles are considered duplicates.

    Triggers:
    - Identical URLs (normalised, scheme and www. stripped).
    - Title token_overlap ≥ ARTICLE_DUP_THRESHOLD.
    """
    url_a = _normalise_url(a.get("url", ""))
    url_b = _normalise_url(b.get("url", ""))
    if url_a and url_a == url_b:
        return True

    overlap = token_overlap(a.get("title", ""), b.get("title", ""))
    return overlap >= ARTICLE_DUP_THRESHOLD


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Return articles with near-duplicates removed (first occurrence kept).

    Complexity: O(n²) on title comparison — acceptable for n ≤ 20 (typical
    Tavily result set).  Does not mutate the input list.
    """
    kept: list[dict] = []
    for candidate in articles:
        if not any(are_duplicate_articles(candidate, seen) for seen in kept):
            kept.append(candidate)
    return kept


def find_similar_in(
    candidate: str,
    seen_titles: list[str],
    threshold: float = TOPIC_SIM_THRESHOLD,
) -> str | None:
    """
    Return the most similar title from ``seen_titles`` if its overlap with
    ``candidate`` is ≥ ``threshold``, else return None.

    When multiple seen titles exceed the threshold, the one with the highest
    overlap is returned.
    """
    best_title: str | None = None
    best_score: float = threshold - 1e-9   # just below threshold

    for seen in seen_titles:
        score = token_overlap(candidate, seen)
        if score >= threshold and score > best_score:
            best_score = score
            best_title = seen

    return best_title


def deduplicate_topics(
    topics: list[dict],
    threshold: float = TOPIC_SIM_THRESHOLD,
) -> list[dict]:
    """
    Return topics with near-duplicate titles removed (first occurrence kept).

    Each topic dict must have at minimum a ``"title"`` key.  The threshold is
    applied with topic_overlap (acronym-expanded Jaccard).

    Note: this may return fewer than 4 items.  Callers that rely on exactly 4
    topics should pass the result to the LLM prompt as context rather than using
    it as a hard post-filter on LLM output.
    """
    kept: list[dict] = []
    kept_titles: list[str] = []

    for topic in topics:
        title = topic.get("title", "")
        if find_similar_in(title, kept_titles, threshold) is None:
            kept.append(topic)
            kept_titles.append(title)

    return kept


def is_fresh_summary(
    new_title: str,
    recent_titles: list[str],
    threshold: float = SUMMARY_SIM_THRESHOLD,
) -> bool:
    """
    Return True when ``new_title`` is NOT too similar to any of the recent titles.

    Use this to check whether a proposed news insight title would be repetitive
    given the last N digest news titles.  Returns True (fresh) when
    ``recent_titles`` is empty.
    """
    return find_similar_in(new_title, recent_titles, threshold) is None


# ── Private helpers ───────────────────────────────────────────────────────────

def _normalise_url(url: str) -> str:
    """Strip scheme and www. prefix for URL equality comparison."""
    try:
        parsed = urlparse(url.lower())
        host = parsed.netloc.removeprefix("www.")
        return host + parsed.path.rstrip("/")
    except Exception:
        return url.lower()
