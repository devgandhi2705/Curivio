"""
Topic clustering and categorization for the AI learning agent.

Classifies topic titles into one of 13 domain categories using keyword
matching.  No ML models — entirely rule-based and deterministic.

Algorithm
---------
1. Tokenize the title: lowercase, strip punctuation, merge hyphenated
   words (e.g. "fine-tuning" → "finetuning") and retain both forms.
2. For each category, count how many of its keywords appear in the token set.
3. Return the category with the highest count.  Ties broken by priority
   order (most-specific categories listed first).
4. If no category scores ≥ 1, return UNCATEGORIZED ("General ML").

Public API
----------
assign_category(title)                      → str   one of CATEGORIES
cluster_topics(topics)                      → dict[str, list[dict]]
get_category_distribution(cat_names)        → dict[str, int]
suggest_unexplored_categories(seen, top_n)  → list[str]
format_category_context(seen_categories)    → str   prompt injection snippet
"""

import re

# ── Category taxonomy ─────────────────────────────────────────────────────────

UNCATEGORIZED = "General ML"

# Priority order: more specific / less ambiguous categories first.
# When two categories tie on keyword count, the one that appears earlier wins.
CATEGORY_PRIORITY: list[str] = [
    "Finance AI",           # domain-specific; very unlikely to false-positive
    "Reinforcement Learning",
    "AI Safety",
    "AI Agents",
    "Vector Databases",     # has product names (faiss, pinecone, chroma, …)
    "RAG & Retrieval",
    "Multimodal AI",
    "Computer Vision",
    "LLM Infrastructure",
    "LLM Training",
    "NLP Foundations",
    "ML Engineering",
    UNCATEGORIZED,          # fallback — always last
]

CATEGORIES: list[str] = CATEGORY_PRIORITY  # alias for external use

# One frozenset of discriminating keyword tokens per category.
# Tokens are matched against the de-hyphenated + raw token set of the title,
# so both "fine-tuning" and "finetuning" match the keyword "finetuning".
_CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "Finance AI": frozenset({
        "finance", "financial", "trading", "market", "stock",
        "portfolio", "quantitative", "hedge", "banking", "investment",
        "fintech", "returns",
    }),
    "Reinforcement Learning": frozenset({
        "reinforcement", "policy", "reward", "environment",
        "exploration", "dqn", "ppo", "actorcritic", "qlearning", "sarsa",
        "bandits", "episodic",
    }),
    "AI Safety": frozenset({
        "safety", "interpretability", "fairness", "bias",
        "transparency", "explainability", "jailbreak",
        "hallucination", "redteaming", "constitutional",
        "alignment", "robustness",
    }),
    "AI Agents": frozenset({
        "agent", "agents", "autonomous", "planning", "orchestration",
        "agentic", "workflow", "multiagent", "function", "tool",
        "react", "reflection",
    }),
    "Vector Databases": frozenset({
        "vector", "faiss", "pinecone", "chroma", "weaviate",
        "milvus", "qdrant", "pgvector", "ann", "approximate", "similarity",
    }),
    "RAG & Retrieval": frozenset({
        "rag", "retrieval", "reranking", "hybrid", "sparse", "dense",
        "bm25", "chunking", "document", "rerank", "indexing",
    }),
    "Multimodal AI": frozenset({
        "multimodal", "visionlanguage", "clip", "vlm", "imagecaption",
        "audiovisual", "imagebinding", "imagebind",
    }),
    "Computer Vision": frozenset({
        "diffusion", "detection", "segmentation", "vit",
        "convolution", "stablediffusion", "denoising",
        "generative", "image2image",
    }),
    "LLM Infrastructure": frozenset({
        "inference", "serving", "quantization", "latency",
        "throughput", "batching", "speculative", "decoding",
        "vllm", "onnx", "tensorrt", "triton", "kvcache", "flash",
        "distillation", "pruning",
    }),
    "LLM Training": frozenset({
        "pretraining", "finetuning", "lora", "peft", "rlhf",
        "sft", "instruction", "continual", "catastrophic",
    }),
    "NLP Foundations": frozenset({
        "tokenization", "tokenizer", "attention", "transformer",
        "bert", "positional", "vocabulary", "semantic", "embedding",
    }),
    "ML Engineering": frozenset({
        "mlops", "monitoring", "distributed", "wandb",
        "mlflow", "experiment", "reproducibility", "deployment",
        "cicd", "lineage", "versioning",
    }),
    UNCATEGORIZED: frozenset(),  # fallback — matches nothing
}

# Minimum keyword matches required before a category is considered a real match.
_MIN_MATCH_COUNT: int = 1


# ── Tokenisation ──────────────────────────────────────────────────────────────

def _title_tokens(text: str) -> frozenset[str]:
    """
    Return a frozenset of cleaned tokens from a topic title.

    Includes both hyphen-merged tokens (fine-tuning → finetuning) and the
    individual split tokens (fine, tuning), so that either form matches the
    corresponding category keyword.
    """
    lower = text.lower()
    # Merged: collapse hyphens so "fine-tuning" → "finetuning"
    merged  = re.sub(r"-", "", lower)
    # Raw: replace all punctuation with spaces
    raw     = re.sub(r"[^\w\s]", " ", lower)

    tokens: set[str] = set()
    for source in (raw, merged):
        for w in source.split():
            if len(w) >= 3:
                tokens.add(w)
    return frozenset(tokens)


# ── Public API ────────────────────────────────────────────────────────────────

def assign_category(title: str) -> str:
    """
    Return the best-matching category for a topic title.

    Scores each category by counting how many of its keywords appear in the
    title's token set.  The category with the highest count wins; ties are
    broken by position in CATEGORY_PRIORITY (earlier = higher priority).

    Returns UNCATEGORIZED when no category scores ≥ _MIN_MATCH_COUNT.
    """
    tokens = _title_tokens(title)
    best_category = UNCATEGORIZED
    best_score    = _MIN_MATCH_COUNT - 1   # anything ≥ _MIN_MATCH_COUNT beats this

    for category in CATEGORY_PRIORITY:
        keywords = _CATEGORY_KEYWORDS.get(category, frozenset())
        score    = len(tokens & keywords)
        if score > best_score:
            best_score    = score
            best_category = category

    return best_category


def cluster_topics(topics: list[dict]) -> dict[str, list[dict]]:
    """
    Group a list of topic dicts by their assigned category.

    Each topic dict must have a ``"title"`` key.  Topics that lack a
    ``"category"`` field are assigned one on the fly.

    Returns a dict keyed by category name, values are lists of topic dicts.
    Only categories with at least one topic are included.
    """
    clusters: dict[str, list[dict]] = {}
    for topic in topics:
        cat = topic.get("category") or assign_category(topic.get("title", ""))
        clusters.setdefault(cat, []).append(topic)
    return clusters


def get_category_distribution(category_names: list[str]) -> dict[str, int]:
    """
    Count occurrences of each category in a flat list of category name strings.

    Useful for summarising how many of the user's liked topics fall into each
    category, without needing the full topic dicts.
    """
    dist: dict[str, int] = {}
    for name in category_names:
        dist[name] = dist.get(name, 0) + 1
    return dist


def suggest_unexplored_categories(
    seen_categories: list[str],
    top_n: int = 3,
) -> list[str]:
    """
    Return the highest-priority categories not yet present in ``seen_categories``.

    "Seen" means the user has at least one positively-rated topic in that
    category.  This drives diversity — the prompt can tell the LLM to consider
    topics from underexplored categories.

    ``UNCATEGORIZED`` is never suggested.
    """
    seen_set = set(seen_categories)
    return [
        cat for cat in CATEGORY_PRIORITY
        if cat != UNCATEGORIZED and cat not in seen_set
    ][:top_n]


def format_category_context(seen_categories: list[str]) -> str:
    """
    Format a category diversity signal for injection into the learning prompt.

    Returns an empty string when there is no history to report.

    Example output:
        Category coverage: LLM Training (3), RAG & Retrieval (2)
        Suggest exploring: AI Agents, LLM Infrastructure, Reinforcement Learning
    """
    if not seen_categories:
        return ""

    dist = get_category_distribution(seen_categories)
    coverage = ", ".join(
        f"{cat} ({count})"
        for cat, count in sorted(dist.items(), key=lambda x: -x[1])
    )

    unexplored = suggest_unexplored_categories(list(dist.keys()), top_n=3)

    lines = [f"Category coverage: {coverage}"]
    if unexplored:
        lines.append(
            f"Consider exploring these under-represented categories: {', '.join(unexplored)}"
        )
    return "\n".join(lines)
