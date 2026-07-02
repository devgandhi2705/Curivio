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

Near-duplicate detection (Phase 7.3)
--------------------------------------
Composite score: 0.25 * title_sim + 0.60 * content_sim + 0.15 * entity_sim
Fires at NEAR_DUP_THRESHOLD = 0.50.  Catches syndicated stories (Reuters on
reuters.com vs yahoo.com) even when titles differ significantly.

Public API
----------
token_overlap(a, b)                              → float  [0, 1] Jaccard
are_duplicate_articles(a, b)                     → bool
deduplicate_articles(articles)                   → list[dict]
find_similar_in(candidate, seen, threshold)      → str | None
deduplicate_topics(topics, threshold)            → list[dict]
is_fresh_summary(new_title, recent, threshold)   → bool
duplicate_score(a, b)                            → float  [0, 1] composite
deduplicate_ranked(articles, threshold)          → list[dict]  keeps best-scored
deduplicate_by_story(articles, threshold)        → list[dict]  story-level, keeps highest-ranked
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

# Near-duplicate: composite title+content+entity score above which articles
# are considered to cover the same story (e.g. Reuters vs Yahoo syndicated).
# 0.50 calibrated so syndicated articles (same content, different headline) pass
# while independently written articles on the same topic do not.
NEAR_DUP_THRESHOLD: float = 0.50

# Story-cluster: title token overlap above which two articles are grouped as
# covering the same story concept (lower than NEAR_DUP_THRESHOLD because
# we compare titles only, not full content).
# Also groups articles that share an exact retrieval_query (same search → same story).
STORY_CLUSTER_THRESHOLD: float = 0.35

# Weights for the composite near-duplicate score.
# Title weight is low because syndicators (Yahoo, MSN) often rewrite headlines
# while copying body text verbatim.  Content is the authoritative signal.
_TITLE_WEIGHT:   float = 0.25
_CONTENT_WEIGHT: float = 0.60
_ENTITY_WEIGHT:  float = 0.15

# Maximum content tokens to use for content overlap (performance ceiling).
_CONTENT_TOKEN_LIMIT: int = 300


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


# ── Near-duplicate detection (Phase 7.3) ─────────────────────────────────────

def _extract_entities(text: str) -> frozenset[str]:
    """
    Naive named-entity proxy: capitalized words ≥ 4 chars (after stripping
    punctuation) that are not stop words.  Captures organizations, place names,
    proper nouns.  Both false positives (sentence-start words) cancel out when
    comparing overlaps between two similar texts — the ratio stays stable.
    """
    raw = re.findall(r'\b[A-Z][a-zA-Z]{3,}\b', text)
    return frozenset(w.lower() for w in raw if w.lower() not in _STOP_WORDS)


def _content_overlap(a: dict, b: dict) -> float:
    """
    Jaccard similarity on the first _CONTENT_TOKEN_LIMIT tokens of each
    article's content field.  Returns 0.0 when either article has no content.
    """
    content_a = a.get("content") or ""
    content_b = b.get("content") or ""
    if not content_a or not content_b:
        return 0.0
    tokens_a = set(_raw_tokens(content_a)[:_CONTENT_TOKEN_LIMIT])
    tokens_b = set(_raw_tokens(content_b)[:_CONTENT_TOKEN_LIMIT])
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _entity_overlap(a: dict, b: dict) -> float:
    """Jaccard on extracted named-entity proxies from title + content."""
    text_a = (a.get("title") or "") + " " + (a.get("content") or "")[:800]
    text_b = (b.get("title") or "") + " " + (b.get("content") or "")[:800]
    ents_a = _extract_entities(text_a)
    ents_b = _extract_entities(text_b)
    if not ents_a and not ents_b:
        return 0.0
    if not ents_a or not ents_b:
        return 0.0
    return len(ents_a & ents_b) / len(ents_a | ents_b)


def duplicate_score(a: dict, b: dict) -> float:
    """
    Composite near-duplicate score in [0, 1].

    Formula:  0.25 * title_sim + 0.60 * content_sim + 0.15 * entity_sim

    Score ≥ NEAR_DUP_THRESHOLD (0.50) means the two articles cover the same
    story and one should be discarded.  Use deduplicate_ranked() to act on this.
    """
    title_sim   = token_overlap(a.get("title", ""), b.get("title", ""))
    content_sim = _content_overlap(a, b)
    entity_sim  = _entity_overlap(a, b)
    return round(
        _TITLE_WEIGHT   * title_sim
        + _CONTENT_WEIGHT * content_sim
        + _ENTITY_WEIGHT  * entity_sim,
        3,
    )


def deduplicate_ranked(
    articles:  list[dict],
    threshold: float = NEAR_DUP_THRESHOLD,
) -> list[dict]:
    """
    Cluster near-duplicate articles and keep one per cluster.

    Keeps the highest-scored article in each cluster (by _retrieval_score).
    Tags the winner with `duplicate_score` (max pairwise score vs discarded
    cluster members, so downstream code knows how strongly it dominated).
    Merges missing metadata from discarded articles into the winner.

    Articles with duplicate_score = 0.0 had no near-duplicate in the batch.

    Complexity: O(n²) pairwise — acceptable for n ≤ 30 (typical filtered set).
    """
    n = len(articles)
    if n <= 1:
        for art in articles:
            art.setdefault("duplicate_score", 0.0)
        return list(articles)

    # Union-Find for clustering
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pair_scores: dict[tuple[int, int], float] = {}

    for i in range(n):
        for j in range(i + 1, n):
            ds = duplicate_score(articles[i], articles[j])
            if ds >= threshold:
                pair_scores[(i, j)] = ds
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[ri] = rj

    # Build clusters keyed by root
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = _find(i)
        clusters.setdefault(root, []).append(i)

    result: list[dict] = []
    for members in clusters.values():
        if len(members) == 1:
            art = articles[members[0]]
            art.setdefault("duplicate_score", 0.0)
            result.append(art)
            continue

        # Keep article with highest retrieval score (pre-ranking quality proxy)
        members.sort(
            key=lambda i: float(articles[i].get("_retrieval_score") or 0.0),
            reverse=True,
        )
        winner_idx = members[0]
        winner     = articles[winner_idx]

        # Compute max pairwise duplicate_score for winner vs discarded members
        max_ds = 0.0
        for j in members[1:]:
            key = (min(winner_idx, j), max(winner_idx, j))
            ds  = pair_scores.get(key) or duplicate_score(winner, articles[j])
            if ds > max_ds:
                max_ds = ds
        winner["duplicate_score"] = round(max_ds, 3)

        # Merge non-empty fields from discarded articles into winner
        for j in members[1:]:
            discarded = articles[j]
            for field in ("published_date", "domain", "source_type",
                          "retrieval_query", "author"):
                if not winner.get(field) and discarded.get(field):
                    winner[field] = discarded[field]

        result.append(winner)

    return result


def deduplicate_by_story(
    articles:  list[dict],
    threshold: float = STORY_CLUSTER_THRESHOLD,
) -> list[dict]:
    """
    Cluster articles by story concept and keep one per cluster.

    Two articles are placed in the same cluster when:
      (a) Both have a non-empty retrieval_query AND they share the same one, OR
      (b) token_overlap(title_a, title_b) >= threshold.

    Rule (a) is the primary signal: articles fetched by the same search query
    are almost always covering the same story.  Rule (b) catches cross-query
    near-duplicates at a lower bar than NEAR_DUP_THRESHOLD (title-only, not
    full-content composite).

    Keeps the article with the highest _rank_score per cluster.
    Preserves the original rank order in the output.

    Must be called AFTER rank_articles() so _rank_score is populated.
    """
    n = len(articles)
    if n <= 1:
        return list(articles)

    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        q_i = (articles[i].get("retrieval_query") or "").strip()
        p_i = (articles[i].get("_perspective")    or "").strip()
        for j in range(i + 1, n):
            q_j = (articles[j].get("retrieval_query") or "").strip()
            p_j = (articles[j].get("_perspective")    or "").strip()
            same_query = bool(q_i and q_j and q_i == q_j)
            if not same_query:
                sim = token_overlap(
                    articles[i].get("title") or "",
                    articles[j].get("title") or "",
                )
                if sim < threshold:
                    # T7 (Phase 9.3.2): also cluster same editorial angle with
                    # moderate title overlap — prevents keeping multiple articles
                    # covering the same story mechanism from the same angle.
                    same_angle = bool(p_i and p_j and p_i == p_j)
                    if not (same_angle and sim >= 0.25):
                        continue
            ri, rj = _find(i), _find(j)
            if ri != rj:
                parent[ri] = rj

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(_find(i), []).append(i)

    result: list[dict] = []
    for members in clusters.values():
        if len(members) == 1:
            result.append(articles[members[0]])
            continue
        members.sort(
            key=lambda idx: float(articles[idx].get("_rank_score") or 0.0),
            reverse=True,
        )
        result.append(articles[members[0]])

    rank_position = {id(a): pos for pos, a in enumerate(articles)}
    result.sort(key=lambda a: rank_position.get(id(a), 9999))
    return result
