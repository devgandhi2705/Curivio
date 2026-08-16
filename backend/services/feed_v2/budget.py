"""
Feed v2 token budget — per-model input budgeting + rank-ordered source packing.

input_budget(m) = min(context_window - max_output, tpm_ceiling) * safety_margin

HARD RULE (asserted in tests/test_feed_v2_budget.py and the __main__ self-check
below): on any section_writer call, packed source content must be >= 60% of the
input budget. Legacy allocated ~1,500 of ~8,000 input tokens (~19%) to sources;
this floor exists specifically so v2 never reproduces that starvation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Sources must get at least this share of a section_writer call's input budget.
SECTION_WRITER_SOURCE_FLOOR = 0.60

# ponytail: ~4 chars/token heuristic, no tokenizer dependency. Good enough for
# budgeting headroom; swap for a real tokenizer only if a leg starts truncating
# mid-token in production.
_CHARS_PER_TOKEN = 4


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))


def truncate_to_tokens(text: str, n_tokens: int) -> str:
    if n_tokens <= 0:
        return ""
    return text[: n_tokens * _CHARS_PER_TOKEN]


@dataclass(frozen=True)
class ModelBudget:
    context_window: int
    tpm_ceiling: int
    max_output: int
    safety_margin: float


# ponytail: ceilings are conservative estimates (context windows are real; TPM
# ceilings approximate the providers' per-minute caps). Tune against live 429
# headroom if budgeting proves too tight/loose — the 60% rule is independent of
# the exact numbers.
MODEL_BUDGETS: dict[str, ModelBudget] = {
    "gemini-3-flash-preview": ModelBudget(context_window=1_000_000, tpm_ceiling=250_000, max_output=8_192, safety_margin=0.9),
    "gemini-3.1-flash-lite":  ModelBudget(context_window=1_000_000, tpm_ceiling=250_000, max_output=8_192, safety_margin=0.9),
    "nemotron-nano-30b":      ModelBudget(context_window=128_000,   tpm_ceiling=200_000, max_output=8_192, safety_margin=0.9),
    "nemotron-super-120b":    ModelBudget(context_window=128_000,   tpm_ceiling=200_000, max_output=8_192, safety_margin=0.9),
}


def input_budget(model_short: str) -> int:
    """Usable input-token budget for a model: whichever of the context-minus-output
    room or the per-minute ceiling binds first, scaled by the safety margin."""
    b = MODEL_BUDGETS[model_short]
    return int(min(b.context_window - b.max_output, b.tpm_ceiling) * b.safety_margin)


def section_writer_source_floor(model_short: str) -> int:
    """Minimum tokens that MUST go to source content on a section_writer call.
    Rounded UP so the packed floor is always >= 60% of the input budget, never
    a sub-token fraction under it."""
    return math.ceil(input_budget(model_short) * SECTION_WRITER_SOURCE_FLOOR)


def _source_text(source: dict) -> str:
    """Rank-ordered truncation content per tier:
      primary → full extract, mid → key passages, tail → title + one-line abstract.
    """
    tier = source.get("tier", "tail")
    if tier == "primary":
        return source.get("full_text") or source.get("key_passages") or source.get("title", "")
    if tier == "mid":
        return source.get("key_passages") or source.get("abstract") or source.get("title", "")
    title = source.get("title", "")
    abstract = (source.get("abstract", "") or "").split("\n", 1)[0]
    return f"{title} — {abstract}".strip(" —")


_TIER_ORDER = {"primary": 0, "mid": 1, "tail": 2}


def pack_sources(sources: list[dict], token_budget: int) -> dict:
    """Pack ranked sources into `token_budget` tokens, tier-ordered (primaries
    first at full extract, then mid key-passages, then tail title+abstract). The
    piece that would overflow is truncated to exactly fill the remaining budget,
    so an ample source set fills the budget precisely (never over).

    Returns {"text", "tokens", "used_count"}.
    """
    ordered = sorted(
        sources,
        key=lambda s: (_TIER_ORDER.get(s.get("tier", "tail"), 2), -float(s.get("rank_score", 0.0))),
    )
    parts: list[str] = []
    used = 0
    tokens_used = 0
    for src in ordered:
        if tokens_used >= token_budget:
            break
        piece = _source_text(src)
        piece_tokens = count_tokens(piece)
        remaining = token_budget - tokens_used
        if piece_tokens > remaining:
            piece = truncate_to_tokens(piece, remaining)
            piece_tokens = count_tokens(piece)
        if not piece:
            continue
        parts.append(piece)
        tokens_used += piece_tokens
        used += 1
    text = "\n\n".join(parts)
    return {"text": text, "tokens": count_tokens(text), "used_count": used}


def pack_section_writer_sources(model_short: str, sources: list[dict]) -> dict:
    """Section-writer packing: the source token allowance is the 60% floor, so
    any successful pack over an ample source set satisfies the HARD RULE."""
    floor = section_writer_source_floor(model_short)
    return pack_sources(sources, floor)


def _demo() -> None:
    model = "gemini-3-flash-preview"
    ib = input_budget(model)
    floor = section_writer_source_floor(model)
    # Ample source material so packing reaches the floor.
    big = "lorem ipsum " * 100_000
    sources = (
        [{"tier": "primary", "rank_score": 9, "full_text": big}]
        + [{"tier": "mid", "rank_score": 5, "key_passages": big}]
        + [{"tier": "tail", "rank_score": 1, "title": "t", "abstract": "a"}]
    )
    packed = pack_section_writer_sources(model, sources)
    assert packed["tokens"] >= 0.60 * ib, (packed["tokens"], 0.60 * ib)
    assert floor >= 0.60 * ib
    print(f"input_budget={ib}  floor(60%)={floor}  packed={packed['tokens']}  OK")


if __name__ == "__main__":
    _demo()
